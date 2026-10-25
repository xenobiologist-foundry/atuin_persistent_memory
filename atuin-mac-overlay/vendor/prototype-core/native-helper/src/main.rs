//! Minimal version-pinned adapter. All native writes use upstream public APIs.
//! JSON stdin is bounded; stdout contains status/IDs only, never command bodies.
use std::{io::{self, Read}, path::Path, process::Command, fs::{self, OpenOptions}, os::unix::fs::{OpenOptionsExt, PermissionsExt}, sync::Arc};
use atuin_client::{database::Sqlite, history::{History, HistoryId, store::{HistoryStore, HistoryRecord}}, record::sqlite_store::SqliteStore, settings::Settings};
use atuin_common::encryption::paseto_v4;
use atuin_domain::record::{CmdHost, CmdUser, CmdOrigin, RecordTag};
use eyre::{Result, bail, eyre};
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha384};
use time::OffsetDateTime;
include!(concat!(env!("OUT_DIR"), "/migrations.rs"));

#[derive(Deserialize, Default)]
struct Event {
    #[serde(default)] id: String,
    host: String,
    user: String,
    cwd: String,
    session: String,
    #[serde(default = "bash")] shell: String,
    command: String,
    #[serde(default = "zero")] timestamp_ns: String,
    status: Option<i64>,
    duration_ns: Option<i64>,
    #[serde(default)] reconcile: bool,
    #[serde(default)] historical: bool,
}
fn bash() -> String { "bash".into() }
fn zero() -> String { "0".into() }

fn check_database(path: &Path, migrations: &[(i64, &[u8])]) -> Result<()> {
    if !path.exists() { return Ok(()); }
    // Native constructors run migrations. Refuse every existing state whose
    // complete applied migration set differs before calling those constructors.
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    let mut stmt = db.prepare("SELECT version, checksum, success FROM _sqlx_migrations ORDER BY version")?;
    let rows: Vec<(i64, Vec<u8>, bool)> = stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?.collect::<rusqlite::Result<_>>()?;
    if rows.len() != migrations.len() { bail!("incompatible native storage migration count"); }
    for ((version, checksum, success), (expected, sql)) in rows.iter().zip(migrations) {
        if version != expected || !success || checksum.as_slice() != Sha384::digest(sql).as_slice() { bail!("incompatible native storage migration"); }
    }
    Ok(())
}

fn history(event: &Event) -> Result<History> {
    if event.command.len() > 262_144 { bail!("command exceeds supported bound"); }
    if [&event.host, &event.user, &event.cwd, &event.session, &event.command, &event.shell].iter().any(|v| v.contains('\0')) { bail!("invalid NUL"); }
    if event.host.contains(':') || event.user.contains(':') { bail!("native origin cannot safely represent colon"); }
    let timestamp = OffsetDateTime::from_unix_timestamp_nanos(event.timestamp_ns.parse()?)?;
    let origin = CmdOrigin::new(&CmdHost::from(event.host.clone()), &CmdUser::from(event.user.clone()));
    let mut h: History = History::import().timestamp(timestamp).command(event.command.clone()).cwd(event.cwd.clone())
        .session(event.session.clone()).cmd_origin(origin).shell(event.shell.clone())
        .exit(event.status.unwrap_or(-1)).duration(event.duration_ns.unwrap_or(-1)).build().into();
    if !event.id.is_empty() { h.id = event.id.parse()?; }
    Ok(h)
}

fn same_identity(a: &History, b: &History) -> bool {
    a.id == b.id && a.timestamp == b.timestamp && a.command == b.command && a.cwd == b.cwd &&
        a.session == b.session && a.cmd_origin == b.cmd_origin && a.shell == b.shell
}

async fn existing_record(store: &HistoryStore, id: HistoryId) -> Result<(Option<History>, bool)> {
    let mut created: Option<History> = None;
    let mut deleted = false;
    // Unlike HistoryStore::history(), fail on unknown/corrupt records instead
    // of skipping them and incorrectly claiming an uncertain write never ran.
    for record in store.store.all_tagged(&RecordTag::History).await? {
        let version = record.version.clone();
        let clear = record.decrypt(&store.encryption_key)?;
        match HistoryRecord::deserialize(&clear.data, version.as_str())? {
            HistoryRecord::Create(h) if h.id == id => {
                if created.as_ref().is_some_and(|prior| prior != &h) { bail!("conflicting native records for stable identity"); }
                created = Some(h);
            },
            HistoryRecord::Delete(deleted_id) if deleted_id == id => deleted = true,
            _ => (),
        }
    }
    Ok((created, deleted))
}

/// One bounded invocation owns one settings snapshot, writer lock and native
/// connection pools. Per-entry privacy/identity/reconciliation still runs.
struct NativeState {
    settings: Arc<Settings>,
    checked: bool,
    database: Option<Sqlite>,
    store: Option<HistoryStore>,
    _writer_lock: Option<fs::File>,
}

impl NativeState {
    fn new(operation: &str) -> Result<Self> {
        let output = Command::new("atuin").arg("--version").output()?;
        let version = String::from_utf8(output.stdout)?;
        if !output.status.success() || !["atuin 18.24.1", "atuin 18.24.1 (c58d2e993d05be423315f6ae3739e9ab3e45eea5)"].contains(&version.trim()) { bail!("native executable version mismatch"); }
        let settings = Settings::new()?;
        if settings.auto_sync || settings.update_check { bail!("local-only native settings required"); }
        let writer_lock = if ["start", "write", "import", "discard"].contains(&operation) {
            let root = std::env::var("ATUIN_SSH_STATE_DIR").unwrap_or_else(|_| "/state/bridge".into());
            fs::create_dir_all(&root)?;
            fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
            let file = OpenOptions::new().create(true).read(true).write(true).mode(0o600).open(Path::new(&root).join("native-writer.lock"))?;
            file.lock()?;
            Some(file)
        } else { None };
        Ok(Self { settings: Arc::new(settings), checked: false, database: None, store: None, _writer_lock: writer_lock })
    }

    fn check_databases(&mut self) -> Result<()> {
        if !self.checked {
            check_database(Path::new(&self.settings.db_path), HISTORY)?;
            check_database(Path::new(&self.settings.record_store_path), RECORD)?;
            check_database(Path::new(&self.settings.meta.db_path), META)?;
            self.checked = true;
        }
        Ok(())
    }

    async fn database(&mut self) -> Result<Sqlite> {
        self.check_databases()?;
        if self.database.is_none() {
            self.database = Some(Sqlite::new(&self.settings.db_path, self.settings.local_timeout).await?);
        }
        Ok(self.database.as_ref().unwrap().clone())
    }

    async fn store(&mut self) -> Result<HistoryStore> {
        self.check_databases()?;
        if self.store.is_none() {
            let store = SqliteStore::new(&self.settings.record_store_path, self.settings.local_timeout).await?;
            let key = paseto_v4::Key::try_load_or_generate(&self.settings.key_path)?;
            self.store = Some(HistoryStore::new(store, self.settings.host_id().await?, key));
        }
        Ok(self.store.as_ref().unwrap().clone())
    }
}

async fn run(operation: &str, event: Event, native: &mut NativeState) -> Result<Value> {
    let settings = native.settings.clone();
    if operation == "check" {
        check_database(Path::new(&settings.db_path), HISTORY)?;
        check_database(Path::new(&settings.record_store_path), RECORD)?;
        check_database(Path::new(&settings.meta.db_path), META)?;
        return Ok(json!({"compatible": true, "version": "18.24.1", "history_db_path": settings.db_path}));
    }
    if operation == "discard" {
        check_database(Path::new(&settings.db_path), HISTORY)?;
        if !Path::new(&settings.db_path).exists() { return Ok(json!({"state": "filtered"})); }
        let id: HistoryId = event.id.parse()?;
        let db = Sqlite::new(&settings.db_path, settings.local_timeout).await?;
        if let Some(h) = db.load(id).await? {
            // Same pre-record failed-command convention as upstream history end.
            // Never discard a completed entry or undo a user/native tombstone.
            if h.exit == -1 && h.duration == -1 && h.deleted_at.is_none() { db.delete(h).await?; }
        }
        return Ok(json!({"state": "filtered"}));
    }
    let h = history(&event)?;
    let passes_command_filters = h.should_save(&settings);
    let historical = event.historical || operation == "import";
    let unknown_outcome = event.status.is_none_or(|s| s < 0);
    let pending_unknown_outcome = passes_command_filters && !settings.store_failed && historical && unknown_outcome;
    let allowed = passes_command_filters && !pending_unknown_outcome && (settings.store_failed || event.status.is_none_or(|s| s <= 0));
    let defer_until_completion = !settings.store_failed && unknown_outcome && !historical;
    if operation == "filter" { return Ok(json!({"allowed": allowed, "defer_until_completion": defer_until_completion,
        "pending_unknown_outcome": pending_unknown_outcome, "version": "18.24.1"})); }
    if pending_unknown_outcome { return Ok(json!({"state": "pending_unknown_outcome"})); }
    if !allowed { return Ok(json!({"state": "filtered"})); }
    if ["start", "write"].contains(&operation) && defer_until_completion { return Ok(json!({"state": "deferred", "id": h.id.to_string()})); }
    if !["start", "write", "import", "probe"].contains(&operation) { bail!("unsupported operation"); }
    if event.id.is_empty() { bail!("stable native identity required"); }
    if settings.daemon.enabled { bail!("native adapter daemon mode not yet verified"); }
    native.check_databases()?;
    if operation == "probe" && !Path::new(&settings.db_path).exists() { return Ok(json!({"collision": false})); }
    let db = native.database().await?;
    if operation == "probe" {
        let collision = db.range(h.timestamp, h.timestamp).await?.iter().any(|p| p.id != h.id && p.cwd == h.cwd && p.command == h.command);
        return Ok(json!({"collision": collision}));
    }
    let prior = db.load(h.id).await?;
    if let Some(ref prior) = prior {
        if prior.deleted_at.is_some() { return Ok(json!({"state": "deleted", "id": h.id.to_string()})); }
        if !same_identity(prior, &h) { bail!("stable identity conflict"); }
    }
    let reconcile = event.reconcile || (operation == "import" && prior.is_some()) || prior.as_ref().is_some_and(|p| p.exit != -1 || p.duration != -1);
    let mut native_store = None;
    if operation != "start" || reconcile {
        native_store = Some(native.store().await?);
    }
    if reconcile {
        let store = native_store.as_ref().ok_or_else(|| eyre!("native record store unavailable"))?;
        let (created, deleted) = existing_record(&store, h.id).await?;
        if deleted {
            if let Some(prior) = prior { db.delete(prior).await?; }
            return Ok(json!({"state": "deleted", "id": h.id.to_string()}));
        }
        if let Some(saved) = created {
            if !same_identity(&saved, &h) || (operation != "start" && (saved.exit != h.exit || saved.duration != h.duration)) { bail!("native committed metadata conflicts with event"); }
            // Rebuild a missing/stale native view only from the authoritative
            // native record. Never insert the request before checking tombstones.
            if prior.is_none() { db.save(&saved).await?; }
            if db.load(h.id).await?.is_none() { return Ok(json!({"state": "collision", "id": h.id.to_string()})); }
            db.update(&saved).await?;
            return Ok(json!({"state": "committed", "id": h.id.to_string(), "reconciled": true}));
        }
    }
    if prior.is_none() {
        db.save(&h).await?;
        if db.load(h.id).await?.is_none() { return Ok(json!({"state": "collision", "id": h.id.to_string()})); }
    }
    if operation == "start" { return Ok(json!({"state": "started", "id": h.id.to_string()})); }
    let store = native_store.ok_or_else(|| eyre!("native record store unavailable"))?;
    db.update(&h).await?;
    let (record, _) = store.push(h.clone()).await?;
    // Verify native view as native `save` uses INSERT OR IGNORE for uniqueness.
    if db.load(h.id).await?.is_none() { bail!("native visibility verification failed"); }
    Ok(json!({"state": "committed", "id": h.id.to_string(), "record_id": record.to_string()}))
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let result = async {
        let requested = std::env::args().nth(1).ok_or_else(|| eyre!("operation required"))?;
        let operation = requested.strip_suffix("_batch").unwrap_or(&requested);
        let batch = operation != requested;
        if batch && !["filter", "probe", "import"].contains(&operation) { bail!("unsupported batch operation"); }
        let mut raw = Vec::new();
        io::stdin().take(2_097_153).read_to_end(&mut raw)?;
        if raw.len() > 2_097_152 { bail!("event too large"); }
        if batch {
            #[derive(Deserialize)]
            struct Batch { events: Vec<Event> }
            let events: Batch = serde_json::from_slice(&raw)?;
            if events.events.len() > 64 { bail!("batch exceeds supported bound"); }
            let mut native = NativeState::new(operation)?;
            let mut results = Vec::with_capacity(events.events.len());
            for event in events.events {
                results.push(run(operation, event, &mut native).await?);
            }
            return Ok(json!({"results": results}));
        }
        let event: Event = if operation == "check" { Event::default() } else if operation == "discard" {
            let value: Value = serde_json::from_slice(&raw)?;
            Event { id: value.get("id").and_then(Value::as_str).ok_or_else(|| eyre!("identity required"))?.into(), ..Event::default() }
        } else { serde_json::from_slice(&raw)? };
        let mut native = NativeState::new(operation)?;
        run(operation, event, &mut native).await
    }.await;
    match result {
        Ok(reply) => println!("{}", reply),
        Err(_) => { eprintln!("atuin-ssh-native: operation refused; history retained pending"); std::process::exit(1); }
    }
}
