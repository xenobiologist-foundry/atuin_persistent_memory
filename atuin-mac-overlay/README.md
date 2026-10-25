# Atuin Mac Overlay

Run an enhanced local zsh in your current terminal, then use `ssh-overlay` for
temporary destination Bash capture, suggestions and the Mac's native Atuin UI.
Exit SSH to return to the local layer; exit again to return to your parent shell.
The current artifact targets Apple Silicon macOS. Read [STATUS.md](STATUS.md)
for measured acceptance and remaining release gates.

## Build and run

From this directory, with macOS Command Line Tools and Python 3.14 available:

```sh
python3 packaging/build.py
./bin/atuin-layer doctor
./bin/atuin-layer
```

The explicit source build downloads only the SHA256-pinned archives in
`dependencies.lock` and Cargo's locked packages. It installs its Rust toolchain
inside `.build`, leaves system tools alone, and creates
`dist/AtuinMacOverlay-arm64.tar.gz` with an adjacent checksum. Building uses no
parent files or parent Git revision. Runtime needs neither Docker nor Homebrew,
a checkout, user-managed Python, nor an Atuin account.

## Install, upgrade and remove

Unpack the archive anywhere and run its `manage` script:

```sh
./AtuinMacOverlay/manage install
~/.local/bin/atuin-layer doctor
~/.local/bin/atuin-layer
```

Installation defaults to `~/Library/Application Support/AtuinMacOverlay/application`
and creates launchers in `~/.local/bin`. Add that directory to PATH yourself if
desired; no startup file is edited. `manage install --prefix PATH --bin-dir PATH`
supports custom paths, including spaces and Unicode. Run the new package's same
install command to upgrade. Close active layer shells first. Unrelated launchers
or unmanaged destination directories are refused.

```sh
./AtuinMacOverlay/manage remove
```

Removal keeps history/configuration. Automatic Terminal startup is deferred;
manual launch is the supported entry. The Mac's account login shell is unchanged.
The package is a local developer artifact, without Apple notarization or an
Intel/older-OS compatibility claim.

## Commands and keys

Inside the enhanced local shell:

```sh
ssh-overlay my-server
ssh-overlay --bash -- non-bash-account
ssh-overlay --no-autosuggest -- my-server
ssh-overlay -- -F '/path/custom ssh config' my-server
ssh-plain my-server
atuin-layer history import --local --dry-run
atuin-layer history import --target my-server --dry-run
atuin-layer history resume-imports
```

`atuin-ssh connect` is a compatibility alias. Existing `ssh` functions/aliases
are preserved. `/usr/bin/ssh` always provides the plain bypass, including outside
the layer. Explicit commands, noninteractive SSH, forwarding-only, background,
subsystem and unsupported invocations use real OpenSSH unchanged. The app never
disables host-key checking or substitutes SSH authentication.

Local Ctrl-R opens native Atuin in GLOBAL across all shells by default, including
imported remote Bash history. Remote Ctrl-R starts in the remote host/account.
Ctrl-R inside the UI cycles native scopes. Host and user columns show origin. Native Up
uses `filter_mode_shell_up_key_binding` (SESSION by default). Tab inserts, Enter
uses native accept behavior, and Escape cancels. Native keymaps and configuration
remain effective. Right accepts the active editor's suggestion without running
it. Local completion belongs to zsh; remote completion belongs to Bash.

Each local shell and each enhanced SSH shell gets its own session ID. Local
Atuin completion is synchronous before the next prompt. Remote persistence uses
the extracted bounded outbox and native writer. Queries and selected commands
are never sent as shell bootstrap text. Long remote initial queries use inherited
kernel-memory descriptors on Darwin, not `/proc` or a disk query file.

## Data and configuration

One installation's state lives under
`~/Library/Application Support/AtuinMacOverlay/`:

- `atuin/`: native history/record databases, local encryption key and writer ID.
- `bridge/`: outbox, import occurrence ledger and connection provenance.
- `config/config.toml`: effective native Atuin settings for this application.

`ATUIN_LAYER_STATE=/absolute/local/path` selects a disposable or separate store.
Use local Mac storage. Never point live state at SMB/NFS or clone an active
writer identity into another installation. Native sync/update checks and daemon
mode are disabled; existing personal Atuin config/history is not imported.
The private official `atuin` is on PATH inside the layer; the system installation
is left in place. `atuin-ssh-search` is the distinctly named compatibility build.

Edit the app's config for supported native search/key/privacy settings. Privacy
filters run natively before durable bridge payloads. With `store_failed=false`,
unknown/failed remote commands can stay volatile until successful completion;
disconnect may lose those deliberately unpersisted events. Typed foreground
password/read input is outside capture. No automatic reconnect or command replay.

### History search settings: all shells or current shell

Edit `~/Library/Application Support/AtuinMacOverlay/config/config.toml`, or
`$ATUIN_LAYER_STATE/config/config.toml` when using a custom state directory.
New installations use these defaults:

```toml
# Top-level settings: keep these before any [section].
filter_mode = "global"
filter_mode_shell_up_key_binding = "session"

[search]
shells = "all"
```

`shells = "all"` includes commands recorded by zsh, Bash and other shells.
`shells = "auto"` shows commands recorded by the current shell, plus records
with no shell metadata. In the local zsh console, `"auto"` hides remote Bash
commands even when the host scope is GLOBAL. Both values are supported; update
the existing `[search]` section rather than adding a duplicate section.

Host scope and shell filtering are independent. Local Ctrl-R now honors the
native `filter_mode` setting; `"global"` searches every recorded host/account,
while `"host"` limits it to the current host. Up separately honors
`filter_mode_shell_up_key_binding`, which remains SESSION by default. Remote
Ctrl-R and inline suggestions retain their host/account context.

Upgrades preserve existing configuration. To apply the shared-history defaults
to an older installation, run these commands **inside the updated app shell**:

```sh
atuin config set filter_mode global
atuin config set search.shells all
```

To return to current-shell filtering, use `atuin config set search.shells auto`.
The next search reads the new settings. After installing an updated application,
open a new layer shell to load its updated key widgets. No re-import is needed.

Local import uses that shell's configured HISTFILE and decodes extended zsh
timestamps, durations, metabytes and continued multiline records. From outside
the layer, explicitly provide `ATUIN_LAYER_HISTFILE` rather than guessing a file.
Remote import discovers Bash HISTFILE through a separate real OpenSSH PTY.
`--ssh-config FILE` supplies a custom OpenSSH config for remote import. Dry-run
performs bounded native privacy/preflight checks, without importing commands.
Progress is count-only. Repeating an unchanged accepted source snapshot adds no
duplicates; append imports retain repeated occurrences. Interrupted submissions
require explicit `resume-imports`, which reconciles stable IDs and tombstones.
Untimestamped rotation, alias/policy changes and native timestamp collisions have
explicit limits. No Docker history is attached or resumed automatically.

For a coherent backup, close all app shells and imports, then copy the **entire**
state tree, including key/host identity and all databases/WAL files. Restore only
while writers are stopped and do not run the original and restored writer at
the same time. A quiesced restore with native record verification and retained
import deduplication passed the package lifecycle test.

## Destination compatibility

Automatic enhancement keeps the configured shell and requires Bash 5+.
`--bash` uses an already installed Bash 4.4+, without changing the account shell;
4.4 also needs fractional `date '+%s %N'`. Unsupported shells use ordinary SSH.
No remote Python, Atuin, package install or Internet download is required. A
private temporary 3,799,040-byte ble.sh bundle is transferred each connection.
Runtime updates are disabled and upstream licenses are bundled.

Custom PROMPT_COMMAND, an existing editor, DEBUG/functrace conflicts or missing
prerequisites can require GNU Readline fallback, reported in the terminal.
Main-shell normal exit cleans the owned editor directory. SIGKILL, exec and
power loss can leave private temporary files. Nested SSH/sudo/container/tmux
shells are foreground apps; their inner commands/identity are not claimed.

Different endpoints reporting the same native hostname/account remain an
explicit identity limit. Registered collisions hold capture pending and refuse
misleading exact-account search. This does not establish isolation for old or
unregistered/imported rows. No fake hostname mapping is presented as a fix.

## Verify

```sh
python3 packaging/check.py
python3 packaging/check.py --baseline
python3 packaging/fixture.py
docker compose -f compose.test.yaml config --quiet
docker compose -f compose.test.yaml up -d --build destination
python3 packaging/check.py --remote
docker compose -f compose.test.yaml --profile legacy up -d --build destination-bash44
python3 packaging/check.py --legacy
```

Fixture keys are generated by `python3 packaging/fixture.py`; they stay under
ignored `.build` and never enter release archives. Tests use isolated profiles,
histories and owned loopback SSH destinations. No production server is involved.
See [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) and
[docs/PROTOCOL.md](docs/PROTOCOL.md). The baseline snapshot and file hashes are in
`vendor/prototype-core/PROVENANCE.json`; native source changes live in
`native/helper/patch_search.py`. Preserve dependency pins during further work.
