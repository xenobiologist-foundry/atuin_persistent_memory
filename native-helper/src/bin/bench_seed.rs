//! Synthetic disposable benchmark data only. Never installed in production.
use std::{fs, path::PathBuf, time::Instant, os::unix::fs::PermissionsExt};
use atuin_client::{database::Sqlite, history::{History, store::HistoryStore}, record::sqlite_store::SqliteStore, settings::Settings};
use atuin_common::encryption::paseto_v4;
use atuin_domain::record::{CmdHost, CmdUser, CmdOrigin};
use eyre::{Result, bail, eyre};
use serde_json::json;
use time::OffsetDateTime;

#[tokio::main]
async fn main() -> Result<()> {
    if std::env::var("ATUIN_SSH_BENCHMARK").as_deref() != Ok("1") {
        bail!("synthetic benchmark opt-in required");
    }
    let count: usize = std::env::args().nth(1).ok_or_else(|| eyre!("record count required"))?.parse()?;
    if count == 0 || count > 1_000_000 { bail!("record count must be 1..1000000"); }
    let root = PathBuf::from(std::env::var("ATUIN_HOME")?);
    let lexical = root.to_string_lossy();
    if !root.is_absolute() || !(lexical.starts_with("/bench/") || lexical.starts_with("/tmp/atuin-ssh-benchmark-")) ||
        root.components().any(|p| matches!(p, std::path::Component::ParentDir)) {
        bail!("only a dedicated absolute /bench/ or /tmp/atuin-ssh-benchmark-* root is allowed");
    }
    if std::env::var("ATUIN_CONFIG_DIR")? != lexical || std::env::var("ATUIN_SESSION").is_err() {
        bail!("explicit matching native configuration root and benchmark session required");
    }
    if root.exists() && fs::read_dir(&root)?.next().is_some() { bail!("benchmark root must be empty; existing state is never reused"); }
    fs::create_dir_all(&root)?;
    if fs::symlink_metadata(&root)?.file_type().is_symlink() { bail!("benchmark root cannot be a symlink"); }
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    fs::write(root.join("config.toml"), "auto_sync=false\nupdate_check=false\nsearch_mode=\"fuzzy\"\ninline_height=20\n[daemon]\nenabled=false\n")?;
    let settings = Settings::new()?;
    if settings.auto_sync || settings.update_check || settings.daemon.enabled { bail!("local-only benchmark settings required"); }
    let started = Instant::now();
    let db = Sqlite::new(&settings.db_path, settings.local_timeout).await?;
    const BATCH: usize = 5000;
    for start in (0..count).step_by(BATCH) {
        let mut batch = Vec::with_capacity(BATCH.min(count - start));
        for index in start..(start + BATCH).min(count) {
            // 10,000 repeatable command spellings across 64 projects, four
            // hosts, two accounts and 64 sessions. Timestamps/IDs are synthetic.
            let key = index % 10_000;
            let command = match key % 5 {
                0 => format!("git -C /workspace/project-{} status # bench-{key:05}", key % 64),
                1 => format!("rg --line-number 'needle-{key:05}' /workspace/project-{}", key % 64),
                2 => format!("printf 'benchmark-{key:05} λ\\n'"),
                3 => format!("curl --head https://example.invalid/fixture-{key:05}"),
                _ => format!("python -m unittest tests.fixture_{key:05}"),
            };
            let origin = CmdOrigin::new(&CmdHost::from(format!("bench-host-{}", index % 4)), &CmdUser::from(format!("bench-user-{}", index % 2)));
            let mut h: History = History::import()
                .timestamp(OffsetDateTime::from_unix_timestamp_nanos(1_700_000_000_000_000_000 + index as i128 * 1_000_000_000)?)
                .command(command).cwd(format!("/workspace/project-{}/sub-{}", index % 64, index % 8))
                .session(format!("019a0000000070008000{:012x}", index % 64))
                .cmd_origin(origin).shell("bash").exit(if index % 17 == 0 { 1 } else { 0 })
                .duration(1_000_000 + index as i64 % 1_000_000).build().into();
            h.id = format!("00000000000050008000{index:012x}").parse()?;
            if !h.should_save(&settings) { bail!("synthetic command unexpectedly excluded by native privacy policy"); }
            batch.push(h);
        }
        db.save_bulk(&batch).await?;
    }
    let native_history_seconds = started.elapsed().as_secs_f64();
    if db.history_count(false).await? != count as i64 { bail!("native history row-count mismatch"); }
    let store = SqliteStore::new(&settings.record_store_path, settings.local_timeout).await?;
    let key = paseto_v4::Key::try_load_or_generate(&settings.key_path)?;
    let store = HistoryStore::new(store, settings.host_id().await?, key);
    let records_started = Instant::now();
    store.init_store(&db, &settings).await?;
    let native_records_seconds = records_started.elapsed().as_secs_f64();
    println!("{}", json!({"records": count, "unique_command_spellings": count.min(10_000),
        "dataset": "synthetic repeatable commands across 64 projects/4 hosts/2 accounts/64 sessions",
        "native_history_seconds": native_history_seconds, "native_records_seconds": native_records_seconds,
        "total_seconds": started.elapsed().as_secs_f64(), "root": root,
        "writer": "upstream Sqlite::save_bulk + HistoryStore::init_store", "batch_size": BATCH}));
    Ok(())
}
