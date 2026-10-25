# Atuin Mac Overlay

Native Atuin history for a local zsh and its SSH destinations, in your existing
terminal. History and search run on the Mac; remote Bash owns editing, completion
and execution. Apple Silicon only; see [status and TODO](STATUS.md) for remaining gates.

## Install and run

With the release archive in your current directory:

```sh
tar -xzf AtuinMacOverlay-arm64.tar.gz
./AtuinMacOverlay/manage install
~/.local/bin/atuin-layer doctor
~/.local/bin/atuin-layer
```

Install location: `~/Library/Application Support/AtuinMacOverlay/application`.
Launchers: `~/.local/bin`; add it to PATH if desired. Runtime includes Python,
Atuin and editor dependencies; Docker, Homebrew and a source checkout are unnecessary.
Your shell profiles are not edited. The artifact is not signed/notarized.

To build from this source directory instead, with Python 3.14 and macOS Command
Line Tools available:

```sh
python3 packaging/build.py
./bin/atuin-layer
```

The archive is created in `dist/`; downloads and native builds are pinned.
See [development](docs/DEVELOPMENT.md) for tests and independent builds.

## Daily use

Inside the layer, use your existing OpenSSH aliases and credentials:

```sh
ssh-overlay my-server
ssh-overlay --bash -- legacy-server       # select existing Bash 4.4+
ssh-overlay --no-autosuggest -- my-server # use GNU Readline
ssh-plain my-server                      # ordinary OpenSSH
```

Automatic enhancement requires a configured Bash 5+ login shell. `--bash` also
supports non-Bash accounts with an existing compatible Bash. Suggestions use a
temporary 3.8 MB ble.sh bundle; destinations need no Python or Atuin. Unsupported
hooks/prerequisites fall back. Nested SSH/sudo/container/tmux shells are not enhanced.

| Key | Action |
| --- | --- |
| Ctrl-R | Native search: local GLOBAL/all shells; remote host/account |
| Up | Native search with Up-specific scope, SESSION by default |
| Tab / Enter / Escape in search | Insert / native accept / cancel |
| Right Arrow at the prompt | Insert the active inline suggestion |

Exit SSH to return to local zsh; exit again to return to the parent shell.
`/usr/bin/ssh` always bypasses enhancement. Existing `ssh` functions/aliases are preserved.

## History and settings

State root: `~/Library/Application Support/AtuinMacOverlay/`, overridden by
`ATUIN_LAYER_STATE=/absolute/local/path`.

| Path under state root | Contents |
| --- | --- |
| `atuin/` | `history.db`, native records/metadata, local key and writer identity |
| `bridge/` | Outbox, import ledger and connection provenance |
| `config/config.toml` | Native search, key and privacy settings |

Local Ctrl-R honors `filter_mode`. Host scope and shell filtering are independent:

```toml
# Top-level settings, before any [section].
filter_mode = "global"
filter_mode_shell_up_key_binding = "session"

[search]
shells = "all"
```

`shells="all"` includes zsh and remote Bash. `shells="auto"` shows the current
shell plus records without shell metadata; local zsh then hides Bash even in
GLOBAL. Update the existing `[search]` section. Older configs are preserved on
upgrade; apply shared-history settings inside a new layer shell with:

```sh
atuin config set filter_mode global
atuin config set search.shells all
# Optional current-shell filtering: atuin config set search.shells auto
```

The next search reads changes; no re-import is required. Remote search and inline
suggestions keep account context. No account or history server is provisioned;
automatic sync/update checks and daemon mode are disabled. Other installations'
history is independent. See [operations](docs/OPERATIONS.md) for import and backup.

## Update or remove

Close active layer shells/imports, then run the **new** extracted package's
`./AtuinMacOverlay/manage install`. History and config are preserved. Custom
locations use `--prefix PATH --bin-dir PATH` consistently for each install.
`./AtuinMacOverlay/manage remove` removes the managed application/launchers and
keeps history/config. For a custom prefix, pass the same `--prefix PATH`.

Technical references: [architecture](docs/ARCHITECTURE.md),
[protocol](docs/PROTOCOL.md), [compatibility](docs/COMPATIBILITY.md).
