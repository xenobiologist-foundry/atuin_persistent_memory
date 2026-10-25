"""Apply the isolated source-reviewed search extension to pinned upstream only.

Executed inside the Rust Linux build stage. No schema changes. The stock release
binary remains `atuin`; the resulting upstream TUI is `atuin-ssh-search`.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1])


def replace(path, old, new, count=1):
    target = root / path
    value = target.read_text()
    if value.count(old) != count:
        raise RuntimeError(f"pinned source anchor mismatch: {path}")
    target.write_text(value.replace(old, new))


settings = "crates/atuin-client/src/settings.rs"
replace(settings, '    SessionPreload = 5,\n}', '    SessionPreload = 5,\n\n    #[serde(rename = "account")]\n    Account = 6,\n}')
replace(settings, '            Self::Host => "HOST",', '            Self::Host => "HOST",\n            Self::Account => "ACCOUNT",')
replace(settings, '                FilterMode::Global,\n                FilterMode::Host,', '                FilterMode::Global,\n                FilterMode::Account,\n                FilterMode::Host,')

database = "crates/atuin-client/src/database.rs"
replace(database, '    let git_root = utils::in_git_repo(cwd.as_str());', '''    let git_root = if atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1") {
        atuin_common::env::var("ATUIN_SSH_REMOTE_WORKSPACE").ok()
            .filter(|root| root.starts_with('/')).map(PathBuf::from)
    } else { utils::in_git_repo(cwd.as_str()) };''')
replace(database, '            git_root: utils::in_git_repo(entry.cwd.as_str()),', '''            git_root: if atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1") {
                None
            } else { utils::in_git_repo(entry.cwd.as_str()) },''')
replace(database, '                FilterMode::Host => query.and_where(origin_sql_filter(&context.cmd_origin)),', '                FilterMode::Host => query.and_where(origin_sql_filter(&context.cmd_origin)),\n                FilterMode::Account => query.and_where_eq("hostname", quote(context.cmd_origin.as_str())),')
replace(database, '            FilterMode::Host => sql.and_where(origin_sql_filter(&context.cmd_origin)),', '            FilterMode::Host => sql.and_where(origin_sql_filter(&context.cmd_origin)),\n            FilterMode::Account => sql.and_where_eq("hostname", quote(context.cmd_origin.as_str())),')
replace(database, '            FilterMode::Directory => sql.and_where_eq("cwd", quote(&context.cwd)),\n            FilterMode::Workspace => sql.and_where_like_left("cwd", git_root),', '''            FilterMode::Directory => {
                sql.and_where_eq("cwd", quote(&context.cwd));
                if atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1") {
                    sql.and_where_eq("hostname", quote(context.cmd_origin.as_str()));
                }
                &mut sql
            },
            FilterMode::Workspace => {
                if atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1") {
                    sql.and_where_eq("hostname", quote(context.cmd_origin.as_str()));
                    let root = git_root.trim_end_matches('/');
                    let prefix = format!("{root}/");
                    sql.and_where(format!("(cwd = {} OR substr(cwd, 1, {}) = {})", quote(&git_root), prefix.chars().count(), quote(prefix)));
                } else { sql.and_where_like_left("cwd", git_root); }
                &mut sql
            },''')

search = "crates/atuin/src/command/client/search.rs"
replace(search, '''            atuin_common::env::var("ATUIN_QUERY").map_or_else(
                |_| vec![],''', '''            atuin_common::env::var("ATUIN_SSH_QUERY_FD").ok()
                .filter(|_| atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1"))
                .map(|value| -> eyre::Result<String> {
                    use std::os::fd::FromRawFd as _;
                    use std::io::Read as _;
                    let fd: i32 = value.parse()?;
                    if fd < 3 { eyre::bail!("invalid query descriptor"); }
                    let file = unsafe { std::fs::File::from_raw_fd(fd) };
                    let mut text = String::new();
                    file.take(262145).read_to_string(&mut text)?;
                    if text.len() > 262144 { eyre::bail!("query too large"); }
                    Ok(text)
                }).transpose()?
                .or_else(|| atuin_common::env::var("ATUIN_QUERY").ok()).map_or_else(
                || vec![],''')
replace(search, '        settings.shell_up_key_binding = self.shell_up_key_binding;', '''        // The compatibility binary always offers ACCOUNT and HOST as distinct
        // native modes, including when an old config lists only stock scopes.
        if atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1") && !settings.search.filters.contains(&FilterMode::Account) {
            settings.search.filters.insert(0, FilterMode::Account);
        }
        settings.shell_up_key_binding = self.shell_up_key_binding;''')

interactive = "crates/atuin/src/command/client/search/interactive.rs"
replace(interactive, '''    let accept;
    let result = 'render: loop {''', '''    let accept;
    let mut atuin_ssh_ready_sent = false;
    let result = 'render: loop {''')
replace(interactive, '''        let initial_input = app.search.input.as_str().to_owned();''', '''        // Notify the owning relay only after terminal negotiation, the first
        // native query, and the first complete results frame. Input sent before
        // this point can be consumed by terminal setup rather than the widget.
        if !atuin_ssh_ready_sent {
            atuin_ssh_ready_sent = true;
            if atuin_common::env::var("ATUIN_SSH_REMOTE_CONTEXT").as_deref() == Ok("1") {
                if let Ok(fd) = atuin_common::env::var("ATUIN_SSH_READY_FD") {
                    let fd: i32 = fd.parse()?;
                    if fd < 3 { eyre::bail!("invalid widget readiness descriptor"); }
                    use std::io::Write as _;
                    use std::os::fd::FromRawFd as _;
                    // This descriptor is transferred by the owning relay.
                    let mut ready = unsafe { std::fs::File::from_raw_fd(fd) };
                    ready.write_all(b"READY\\n")?;
                    ready.flush()?;
                }
            }
        }

        let initial_input = app.search.input.as_str().to_owned();''')
replace(interactive, '''fn selection_output(
''', '''fn atuin_ssh_insert_output(command: String) -> String {
    if !command.is_empty() && atuin_common::env::var("ATUIN_SSH_RESULT_PROTOCOL").as_deref() == Ok("2") {
        format!("__atuin_insert__:{command}")
    } else { command }
}

fn selection_output(
''')
replace(interactive, '''        Some(query) => format!("{} {command}", query.trim_end()),
        None if accept => format!("{ACCEPT_PREFIX}{command}"),
        None => command,''', '''        Some(query) => atuin_ssh_insert_output(format!("{} {command}", query.trim_end())),
        None if accept => format!("{ACCEPT_PREFIX}{command}"),
        None => atuin_ssh_insert_output(command),''')
replace(interactive, '''            Ok(app.search.input.into_inner())''', '''            Ok(atuin_ssh_insert_output(app.search.input.into_inner()))''')
