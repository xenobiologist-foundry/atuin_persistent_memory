# Atuin Mac Overlay: implementation handoff

Prepared 2026-10-24 for a fresh Codex conversation running natively on macOS.

## Start here

Read this document completely, inspect applicable `AGENTS.md` instructions and
the Mac environment, then implement the staged plan below. This is the agreed
Mac product brief, with the relevant Linux prototype experience embedded. Do not
require the previous conversation to understand the work.

This folder currently contains a handoff, not a working Mac application. Begin
implementation in `atuin-mac-overlay/`. Keep that project self-contained and
preserve unrelated work in the surrounding repository. The older root
`ATUIN_SSH_CODEX_PROMPT.md` describes the Linux/Docker prototype; it is source
background, not an instruction to ship Docker, a Linux shell or an SSH server as
the Mac application's entry layer.

Native macOS shell, Python and Rust execution are appropriate for this project.
The earlier requirement to execute Linux work in containers applied to development
from native Windows. Use Linux containers or authorized Linux machines as SSH
test destinations; prove the application itself on native macOS.

Do not stop after a design, scaffolding, local-only Atuin demo or mocked SSH UI.
Work toward the complete local-and-remote interaction, with installed-package
verification and explicit remaining compatibility limits.

## Agreed product and scope

The operator opens their usual terminal and runs this console application.
The application immediately opens a fully enhanced local zsh shell. From its
first usable prompt, local commands are captured in native Atuin, native history
search works, and inline suggestions are available. SSH is not required to
activate any of those features.

The operator can work locally, enter an enhanced SSH destination, exit back to
the enhanced local shell and continue using the same history. Exiting the app
returns to the original parent shell with terminal modes restored. The app is a
normal nested shell experience in the existing terminal window, not a new
terminal emulator or a graphical window manager.

User decisions already settled:

1. Preserve the Mac operator's normal zsh setup. Use native Atuin and bundled
   `zsh-autosuggestions` locally. Do not switch the Mac entry shell to Bash.
2. Remote autosuggestions use **only temporary ble.sh in an existing compatible
   remote Bash**. Do not implement or plan a remote zsh-autosuggestions adapter.
   Do not upload zsh or require its installation across a server fleet.
3. Version one enhances SSH sessions launched from the Mac entry layer. SSH
   launched inside a remote shell is outside scope. Nested sudo/su shells,
   container shells and existing tmux/screen sessions remain foreground
   applications, with no claimed inner capture or inferred inner identity.
4. Starting the console app manually must be seamless. Automatic launch when
   Terminal opens is an optional later convenience, not a prerequisite.
5. Native Atuin history and the real native search UI live on the Mac. Remote
   Bash owns editing, completion and execution. Nothing is permanently installed
   on destinations, and their startup files are not modified.
6. One Mac installation has one local native history store shared by its app
   sessions and terminal tabs. Separate Macs and the old Docker hub have
   independent histories unless an explicit migration/import is performed.
7. No Atuin account, login, hosted/local synchronization server, telemetry, AI
   service or external history service. Intentional user networking, including
   OpenSSH, curl, Git, DNS and VPN use, remains functional.

## User experience and command surface

Use `atuin-layer` as the initial launcher name and `ssh-overlay` as the explicit
enhanced SSH command. These names are provisional; naming must not block the
implementation. The project directory is `atuin-mac-overlay`.

Proposed interaction, not commands already implemented:

```text
existing terminal shell
  $ atuin-layer
      enhanced local zsh: native capture, Ctrl-R/Up, inline suggestions
      $ local-command
      $ ssh-overlay my-server
          enhanced destination Bash: temporary ble.sh
          remote-command
          Ctrl-R -> real native Atuin UI on Mac -> same remote editor
          exit
      enhanced local zsh: local and remote history remain available
      $ exit
existing terminal shell
```

Initial CLI surface:

```sh
atuin-layer
ssh-overlay my-server
ssh-overlay --bash -- legacy-or-non-bash-account
ssh-overlay --no-autosuggest -- my-server
atuin-layer history import --local --dry-run
atuin-layer history import --target my-server --dry-run
atuin-layer history resume-imports
atuin-layer doctor
```

Define the final parser consistently and test it. Retain an `atuin-ssh connect`
compatibility alias if inexpensive. An ordinary `ssh` wrapper may be enabled
inside the entry shell after the explicit command works; preserve an existing
custom function and always provide an explicit bypass to real OpenSSH.

Search and editing contract:

- Local and remote Ctrl-R/Up invoke actual native Atuin behavior and honor
  supported native keymap, Up-specific scope and insert/accept/cancel settings.
- Search can browse all recorded hosts with visible context. Remote search starts
  in the exact remote host/account context; global search removes that restriction.
- Inline suggestions default to the current host/account. Right accepts a
  suggestion without execution; Enter executes the completed command. Preserve
  normal editing and word acceptance where supported by the active editor.
- Local Tab completion uses the Mac environment. Remote Tab completion uses the
  destination environment. The Mac must not pretend to complete remote paths.
- Preserve partially typed input, cursor, mark and keymap on search cancellation.
- Every instrumented shell has a new native session ID, including concurrent
  tabs; do not inherit one Atuin session ID across distinct shells.
- Capturing the outer `ssh-overlay` command locally and commands executed inside
  its remote shell are different events. Do not double-capture either event.

## Architecture and package boundary

```text
Terminal.app (existing window)
  parent shell
    atuin-layer -> ordinary local zsh + native Atuin + zsh-autosuggestions
      ssh-overlay -> Mac relay -> real system OpenSSH -> destination Bash
                       |                            + temporary ble.sh/bridge
                       + native Atuin UI and native storage on Mac
```

Use the local shell's native zsh line editor and Atuin integration; do not build a
replacement local editor. Add the relay/PTY machinery around onward SSH where it
is needed. Reuse the tested Python orchestration and native compatibility
components initially, with a small explicit platform layer for Darwin behavior.

Suggested eventual contents:

```text
atuin-mac-overlay/
  HANDOFF.md
  README.md
  AGENTS.md
  src/                       application, CLI, platform adapters
  shell/                     local zsh and temporary remote Bash integration
  native/                    pinned Atuin compatibility source/builds
  vendor/prototype-core/     bounded baseline snapshot and provenance
  dependencies.lock
  packaging/                 build, install, upgrade, removal
  tests/                     native Mac and Linux-destination tests
  docs/                      decisions, protocol, compatibility, delivery status
```

The independence test is mandatory: copy this folder outside the parent checkout
and build, test, package and run it there. No parent imports, symlinks, editable
installs pointing upward, parent build scripts or runtime dependency on the Linux
project are allowed.

During initial extraction only, read selected prototype files from the pinned
baseline below. Copy the necessary dependency closure and relevant tests into
this folder, with source revision, file list, licenses and checksums. Do not copy
the entire repository or require a fresh Mac session to maintain both projects.
This handoff does not itself contain that source snapshot; extraction is Stage 1.

Separate source and release requirements:

- An explicit source build may download checksum-pinned upstream dependencies.
  Keep dependency/build recipes inside this folder.
- The release must include native Atuin, the compatibility components, a private
  Python runtime if needed, zsh-autosuggestions and the prebuilt remote ble.sh
  bundle. No checkout, Docker, Homebrew or user-managed Python is required at
  runtime. Reuse the Mac's existing zsh and real OpenSSH.
- Use per-user installation and application data. A suitable starting layout is
  `~/Library/Application Support/AtuinMacOverlay/{atuin,bridge,config}`. Test spaces
  and Unicode in installation, home and state paths. Resolve resources relative
  to the installed application, not the current working directory.
- Keep history, credentials, keys and personal configuration out of source,
  distributable archives, fixtures, transcripts and diagnostic reports.

## Prototype baseline and what it actually proves

Repository: `git@github.com:xenobiologist-foundry/atuin_persistent_memory.git`

Baseline: `0b577c0f8f55e9f0cc37c70b1a74bb466c7c9a72`
(`Add temporary destination ble.sh with hub-native suggestions`). Use this exact
revision for provenance, even if the repository has later unrelated commits.
If the parent checkout is unavailable, retrieve only the selected source from
that revision using the user's normal authorized repository access.

The existing product is a Linux Docker SSH hub. Workstation SSH -> hub -> real
OpenSSH -> destination Bash -> native Atuin UI on the hub -> selection returned
to that same destination editor is working. The new Mac product moves the
hub's local history/UI/relay role into the Mac app and adds the complete local
zsh entry experience. It does not require hub sshd or Docker for daily use.

Recorded Linux evidence, not macOS acceptance:

| Baseline gate | Recorded result |
| --- | --- |
| Modern installed-image aggregate | 177 cases in 236.151 s; OK, 9 expected skips |
| Actual Bash 4.4.23 aggregate | 177 cases in 246.467 s; OK, 1 dedicated-import skip |
| Independent non-root SSH import | Passed in 2.716 s |
| Dedicated temporary remote ble.sh suite | 7 cases on Bash 5.2 in 52.509 s and Bash 4.4.23 in 50.632 s |
| Bundle / native suggestions / relay ownership / custom-prompt fallback | 4 / 7 / 6 / 1 focused cases |
| Offline native and hub-editor observations | 17 + 3 cases; zero observed Internet connect/send attempts |

The original broad two-hop suite explicitly uses the GNU Readline mode. The
seven new remote-editor cases exercise ble.sh. The aggregate is not evidence of
complete ble.sh parity. Remote-editor egress was not separately observed.
Neither those Linux tests nor running them from PowerShell prove native macOS.

The full Linux brief also has unfinished identity, startup, failure and physical
platform gates. Reuse working mechanisms without inheriting claims of a finished
MVP. No current production history or live Docker state is needed for Mac tests.

Initial dependency pins to preserve while porting:

- Stock Atuin 18.24.1, upstream commit
  `c58d2e993d05be423315f6ae3739e9ab3e45eea5`. Native Apple Silicon and Intel release
  assets exist. Keep the official binary and a distinctly named compatibility
  binary; do not silently replace a user's system Atuin.
- Baseline orchestration uses Python 3.14; runtime image used Python 3.14.2.
  Bundle and lock an appropriate macOS build rather than using system Python.
- Native helper baseline builds with Rust 1.95.0 and a checked Cargo lockfile.
- ble.sh release `ble-nightly-20260908+d81fd54`, commit
  `d81fd54feb0d996fdff20dca27eaf0201f7015cc`, upstream archive SHA256
  `7a2445f138e7f099dd5dee749391a8b045646d1b8a605975885be5b34b6b5f7e`.
- Deterministic remote session tar: 3,799,040 bytes, SHA256
  `63a0c475827efb41f8156a28b8e057749c28f03fc4cc9b5989e86b204ee945ee`.
  It includes the disabled updater and upstream licenses.
- Select and lock zsh-autosuggestions during Mac work; it was researched but no
  Mac bundle or tested version was created in this conversation.

Do not combine the initial port with opportunistic dependency upgrades. If a pin
cannot work on the target Mac, record the reason and validate the smallest
necessary update, including native migration compatibility.

## Bounded source extraction map

Paths in this table are baseline source locations, not future parent imports.

| Baseline files | Reuse or adapt |
| --- | --- |
| `src/atuin_ssh/ssh.py` | Conservative OpenSSH argv classification and `ssh -G` evaluation |
| `src/atuin_ssh/relay.py`, `protocol.py` | Real OpenSSH/native UI PTYs, framing, fenced ownership, bounds, READY and RELEASE |
| `src/atuin_ssh/bootstrap.py`, `bash/remote.bash` | Temporary Bash startup, GNU Readline fallback, clocks and capture |
| `src/atuin_ssh/bash/remote_ble.bash`, `bash/blesh_setup.bash`, `blesh.py` | Temporary editor delivery, BLE callbacks, suggestion RPC and cleanup |
| `src/atuin_ssh/atuin.py` | Native search, exact results, privacy checks and bounded suggestion lookup |
| `src/atuin_ssh/history.py`, `importing.py`, `context.py` | Outbox, occurrence ledger, reconciliation, provenance and ambiguity guard |
| `native-helper/src/main.rs`, `build.rs`, `Cargo.toml`, `Cargo.lock`, `patch_search.py` | Native APIs, compatibility checks, ACCOUNT/path scopes and explicit result protocol |
| `docker/build-blesh-bundle.py`, `docker/blesh-package.bash` | Deterministic prebuilt editor bundle and refused runtime updates |
| `config/atuin.toml`, `Dockerfile`, `requirements-build.lock` | Reference pins, local-only settings, build provenance; replace Linux packaging |
| Relevant `tests/` and `tests/pty_client.py` | Extract the test dependency closure; port its driver and fixtures to Mac |

Prioritize tests named `test_remote_autosuggestions`, `test_blesh_bundle`,
`test_native_suggestions`, `test_remote_relay`, `test_remote_startup`,
`test_two_hop`, `test_capture`, `test_terminal`, `test_ssh_integration`,
`test_storage`, `test_context`, and import interruption/transport/batch tests.
Add new real local-zsh and installed-Mac tests. The native benchmark seeding
binary belongs only in test tooling, never in the runtime release.

## Technical contracts and lessons to preserve

### Local startup and zsh

- First prompt is the activation boundary: first-command capture and immediate
  native UI/suggestions must work without a warm-up command or prior SSH login.
- Preserve the user's normal cwd, environment, PATH semantics, SSH agent,
  aliases, functions, prompt, completions, vi/emacs preferences and exit status.
- Integrate after ordinary user configuration at the correct zsh lifecycle point.
  Avoid duplicate startup-file sourcing within one child shell, recursive
  autolaunch and inherited temporary startup paths affecting unrelated shells.
- Handle existing Atuin, zsh-autosuggestions and custom SSH integrations. Use one
  effective Atuin configuration and one capture integration per shell. Do not
  overwrite personal configuration or enable synchronization through an existing
  integration. Demonstrate the supported composition with real profile fixtures.
- Manual repeated app launches can create distinct nested local sessions sharing
  one store. Automatic startup must not recursively create layers.
- Automatic Terminal-profile launch is opt-in, reversible and tested after the
  manual launcher works. Changing the account's login shell is unnecessary.

### Darwin portability

- Replace Linux `os.memfd_create` and `/proc/self/fd` use. The native search patch
  currently opens `/proc/self/fd/<fd>` for READY, and long initial queries use a
  Linux memfd path. Use bounded inherited descriptors with an explicit ownership
  and close policy on Darwin; avoid persisting typed queries as a workaround.
- Port `/state` and `/usr/local/share` resource assumptions, locale discovery,
  child creation, PTY EOF/EIO handling, termios, resize, signals and job control.
  Preserve explicit use of the real OpenSSH executable.
- Validate the Python PTY/fork model on native macOS, including existing worker
  threads. Python documents macOS fork constraints with higher-level system APIs.
  A small native spawner/platform adapter is an option if required; do not
  casually rewrite the entire application or introduce Foundation calls into a
  fragile post-fork child path.
- Detect macOS version and CPU architecture at the start. Deliver native support
  for the actual development Mac first and record its minimum OS target. Claim
  additional architectures only after native builds and installed tests.

### Remote Bash and temporary ble.sh

- Preserve the configured remote shell by default. Baseline automatic enhancement
  requires configured Bash 5+. Explicit `--bash` selects an existing Bash 4.4+
  for that session, including `/bin/sh` accounts. Bash 4.4 needs a working
  `date '+%s %N'` clock utility. Do not install a shell to force compatibility.
- Destinations need no Python, Atuin, network download or persistent agent. Bundle
  transfer needs existing tar, base64 decoding, awk, stty, mktemp and a supported
  SHA256 tool, plus the other basic utilities checked by the receiver.
- Validate regular files, member paths/types/modes, size and checksum before
  transfer. Extract only the matching bounded archive into a private owned
  session directory; scope runtime/cache/state there. Refuse runtime updates.
- Recover queued input through a raw-terminal fence before transferring the
  bundle. Hold new input until editor startup is acknowledged. Never send shell
  bootstrap code as editable terminal input.
- Normal main-shell BLE unload cleans the private directory after upstream
  finalization. Command substitution/subshell unload must not delete parent
  files. `exec`, SIGKILL and power loss can leave private temporary files; do not
  promise universal cleanup or delete unrelated temp directories.
- The current adapter deliberately falls back to GNU Readline for nonempty user
  PROMPT_COMMAND, an existing editor, incompatible DEBUG/functrace or unsupported
  prerequisites. Custom prompt hooks can otherwise cause startup input deadlock
  or foreground `read -e` prompt reuse. Report fallback clearly. Broaden support
  only with actual differential tests.
- BLE uses lifecycle hooks, with a narrowly pinned decoder/unload shim carrying
  the upstream license notice. Preserve binary typeahead and source-pin checks.
  Avoid adding a PRECMD hook casually: it changed the pinned editor's nested-read
  behavior. The tested adapter uses initial attach and exec_end notification.

### SSH, native UI and input ownership

- Invoke real OpenSSH with argv arrays. Preserve normal authentication, host-key
  checking, aliases/config, proxies, jumps, forwarding, multiplexing and exit
  status. Do not reimplement SSH or kill a shared ControlMaster.
- Pass explicit remote commands, SCP/SFTP/subsystems, noninteractive sessions,
  forwarding-only/background/config-query forms and unsupported cases through
  unchanged. Do not reconstruct the original argv from `ssh -G` output.
- The relay has one input owner at a time: SSH, waiting callback or native UI.
  Use session/request generations, ordered fences, HANDOVER and RELEASE. Native
  READY follows negotiation and the first complete results frame; early Enter,
  Tab and arrows must reach the UI rather than being eaten during initialization.
- Never infer commands or prompt eligibility by scraping rendered output. Treat
  remote data as untrusted; frame nonces prevent accidents, not hostile PTY peers.
- Preserve the exact selected command, including Unicode and trailing newlines.
  Explicit insert/accept tags prevent literal reserved-prefix commands being
  misinterpreted. No raw selected-command/newline injection into an ordinary shell.
- Cancellation/timeouts must not return an editor while late protocol DATA can
  still arrive as input. After bundle END may have released ownership, close the
  owned transport rather than injecting an unsolicited abort into a live editor.
- Bound input/output queues and backpressure background output during native UI.
  Restore terminal modes on catchable failures. No automatic command replay or
  reconnect after uncertain completion. A hard kill cannot guarantee restoration.
- Suggestions use one bounded native worker, not a keystroke-blocking query in
  the relay loop. New typing cancels stale results. The baseline bounds are 4 KiB
  prefix / 64 KiB single-line control-free suggestion and 256 KiB native command
  representation; reject unsupported values visibly or safely, never truncate.

### History, identity, import and privacy

- Native Atuin history/record machinery is the source of truth. No substitute
  canonical history database, schema mutation or lookalike TUI. A bridge outbox,
  occurrence ledger and provenance registry are allowed coordination metadata.
- Use the pinned native helper for metadata-correct writes, privacy and replay.
  Version/migration checks must precede write constructors. Initial native
  daemon-backed operation remains unsupported until separately verified.
- Native command formatting trims whitespace. The tested suggestion path uses
  native UUID search, then a bounded read-only lookup of that exact checked row
  to preserve trailing spaces. This does not authorize direct SQL history writes.
- Record actual execution host/account/cwd/session, with connection alias and
  effective endpoint as separate provenance. Directory/workspace scopes must
  include host/account, not match an identical path on another server.
- **Known unresolved identity gap:** different machines can report the same
  hostname/account. Baseline detects some registered endpoint conflicts, holds
  capture pending and refuses misleading exact-account search. Historical,
  unregistered and imported records are not fully protected by that guard.
  Explicit alias/machine mapping must reach the actual native query path before
  claiming full isolation. Do not manufacture fake hostnames or claim that a
  metadata mapping alone solves native scope ambiguity. Keep ambiguous cases
  explicit until tested.
- Preserve true repeated executions. Same literal target/source/unchanged accepted
  snapshot re-import must add no duplicates; append imports add new occurrences.
  Alias, privacy or bounds changes and ambiguous untimestamped rotations do not
  currently carry an unconditional exactly-once guarantee.
- Local import must parse zsh history, including its extended-history timestamps
  and multiline forms. Remote import reads the configured Bash HISTFILE through
  a separate real OpenSSH PTY, with raw mode restored after profiles. Never
  evaluate history contents or assume `~/.bash_history` is the configured file.
- Imports need bounded reads/batches, dry-run, count-only progress, concise
  cancellation and explicit resume. Durably record attempts before submission;
  reconcile uncertain writes with stable IDs and tombstones before replay.
  Preserve unknown historical status/duration; do not fabricate successful exits.
- Apply native privacy policy before durable command payloads. Respect shell
  exclusions, native filters and store_failed policy. Baseline failed/unknown
  commands can remain volatile until successful completion; loss on disconnect
  under that policy is intentional and must be documented.
- Native SQLite and writer state stay on local Mac storage, never a live shared
  SMB/NFS DB. Backup/restore must quiesce writers and preserve the entire native
  state. Do not run independent installations with cloned active writer identity.
- Existing Docker history is an optional explicit migration. Do not silently
  attach it, copy credentials or resume the user's previously canceled real import.

## Delivery stages and exit gates

| Stage | Work | Exit gate |
| --- | --- | --- |
| 1. Standalone baseline | Inspect Mac/instructions, copy the selected source and tests with provenance, establish locks and package layout | This folder builds independently; no upward dependency |
| 2. Native foundation | Build native Atuin/helper/search and private orchestration runtime; port Darwin paths/descriptors/PTY lifecycle | Real native UI works and catchable exits restore the terminal on this Mac |
| 3. Complete local entry | Launch normal zsh, integrate capture/search/autosuggestions before the first prompt, compose user configuration | First local command recorded; immediate Ctrl-R/Up and suggestions work; exit returns to parent |
| 4. Complete onward SSH | Explicit ssh-overlay, real OpenSSH and temporary remote Bash/ble.sh, GNU fallback | Full Mac -> destination -> Mac-native UI -> same remote editor proof, including capture and cancellation |
| 5. Shared memory/import | Local/remote context, global search, concurrent shells, zsh/Bash imports, re-import/resume and identity handling | Correct scopes and provenance, preserved repeated events, tested deduplication boundaries and explicit collision handling |
| 6. Compatibility | Profiles/plugins/keymaps, jobs/apps, output/resize/signals, SSH modes and failure recovery | Evidence-backed compatibility matrix and clear fallbacks; no skipped failure disguised as support |
| 7. Release packaging | Per-user relocatable runtime, dependency licenses, install/upgrade/removal/doctor, optional startup | Runs outside the checkout without Docker/Homebrew/system Python; upgrades retain state |
| 8. Installed acceptance | Repeat important native Mac and actual Linux-destination tests against the release artifact | Reproducible results, residual limits and user run instructions recorded |

Keep source-build downloads separate from runtime behavior. Test with disposable
histories and owned destinations; do not inspect real history or credentials.
Do not change unrelated live Docker resources or erase personal state. Removal
uninstalls integration/application files while retaining history by default.

## First end-to-end milestone: exact demonstration

1. Open Terminal and run the application manually.
2. At its first local prompt, execute a command and retrieve it using real native
   Atuin and a visible inline suggestion. Confirm host/account/cwd and unique
   local session identity; no warm-up command is needed.
3. From that shell, launch ssh-overlay to an authorized Linux Bash destination
   with no Python or Atuin installed there.
4. Execute a remote command and retrieve it through native UI and temporary
   ble.sh suggestions. Confirm remote context and immediate native visibility.
5. Demonstrate suggestion acceptance without execution, native insert, native
   accept and cancel with an existing Unicode buffer/cursor/mark. Test activation
   plus query/navigation/Enter in one input burst.
6. Show that Tab completes a destination-only path. Run foreground read/password
   input and a fullscreen program without interception or capture of their input.
7. Exit remote SSH, remain in the enhanced local shell, and find that remote
   command through global search. Local suggestions still use local context.
8. Exit the app and verify the original shell and terminal modes are usable.
9. Repeat key checks with the installed package outside the repository.

Before claiming version one complete, also cover:

- Actual Mac zsh startup/profile/plugin compatibility and duplicate-hook prevention.
- Bash 5.x and actual 4.4 destinations, explicit --bash and unsupported-shell fallback.
- Two concurrent local/remote sessions sharing memory without sharing session IDs.
- Identical paths on different accounts/hosts, alias equivalence and hostname collision.
- Import dry-run/repeat/append/multiline/interrupt/resume and documented rotation limits.
- Native privacy/deletion/record integrity and coherent backup/restore.
- SSH authentication/config/jump/forwarding/multiplexing and graceful bypass forms.
- Ctrl-C/Z/D, jobs, fullscreen programs, resize, output backpressure, malformed/stale
  frames and disconnects, using installed native Mac execution.
- Startup, key-to-native-UI and suggestion latency measured separately. The baseline
  bundle adds about 3.8 MB per connection; a 3.522 s local PTY transfer observation
  was not an end-to-end network or physical-server startup guarantee.
- Runtime no-account/no-external-history behavior on macOS with an appropriate
  observation method; Linux strace evidence is not a Mac measurement.

## Working and reporting expectations

Use judgement for routine implementation choices and keep moving through the
stages. Previously settled choices above do not need to be asked again. Report
material discoveries, compatibility changes and blocked gates clearly. Keep a
local STATUS with what passed, what failed, what falls back and what remains
unverified. A successful build is not an installed-product acceptance result.

Do not broaden scope into remote zsh, recursive remote SSH, a replacement terminal
emulator, a background sync service or a GUI. First deliver the enhanced local
zsh plus temporary remote Bash/ble.sh experience. The root Linux implementation
and production history are reference material, not runtime dependencies.

## Primary references already checked during planning

- [Atuin 18.24.1 source and macOS release assets](https://github.com/atuinsh/atuin/releases/tag/v18.24.1)
- [Atuin integration with zsh-autosuggestions and ble.sh](https://docs.atuin.sh/18.22/integrations/)
- [zsh-autosuggestions upstream requirements and behavior](https://github.com/zsh-users/zsh-autosuggestions)
- [ble.sh upstream requirements and limitations](https://github.com/akinomyoga/ble.sh)
- [Python PTY documentation, including macOS fork caveat](https://docs.python.org/3.14/library/pty.html)
- [Apple Terminal profile startup command settings](https://support.apple.com/en-mt/guide/terminal/trmlshll/mac)

Verify pinned source and current macOS behavior during implementation. This
document records decisions and prior evidence; it does not claim a Mac build
has already been produced or validated.
