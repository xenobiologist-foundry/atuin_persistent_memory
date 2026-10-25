# Mac status and TODO

Evidence recorded 2026-10-25. Installed local zsh → enhanced SSH → local zsh works.
Full version-one acceptance remains incomplete at the gates below. Documentation
cleanup does not constitute a new full runtime acceptance run.

Tested host: macOS 26.5.2 (25F84), arm64, zsh 5.9, OpenSSH 10.2p1. Bundled Python
3.14.2, Atuin 18.24.1 and Rust-1.95.0-built native components. Deployment target
is macOS 14.0; minimum-OS execution, Intel and signing/notarization are unverified.

## Implemented and verified

- Standalone native build/package, including an independent build outside the
  parent checkout; 52 pinned baseline files with SHA256 provenance.
- Native Darwin PTYs, inherited READY/query descriptors and terminal restoration.
- First local command capture/search/suggestions, profile order, existing
  Atuin/plugin/custom SSH composition, vi setup, Unicode cancel and unique sessions.
- Real Mac SSH to Bash 5.2 and actual Bash 4.4.23, with temporary ble.sh,
  account-scoped suggestions, Right/insert/accept/cancel/Up, burst input,
  destination completion, foreground read/password isolation and cleanup.
- Local GLOBAL/all-shell search selects exact remote/imported Bash commands.
  Native filter_mode is honored; Up remains SESSION; suggestions remain account-scoped.
- Native privacy/deletion/records, zsh multiline/metabyte parsing, local repeat/
  append import, real configured remote HISTFILE, stable-ID/batch recovery and
  quiesced full-state restore retaining import deduplication.
- Installed Ctrl-Z/fg/Ctrl-C, resize, less, disconnect return, ProxyJump command
  pass-through and shared ControlMaster retention.
- Relocatable private runtime, licenses/manifest, install/upgrade/removal with
  history preserved, and installation/home/state paths containing spaces/Unicode.

## Recorded acceptance

| Run | Result |
| --- | --- |
| Independent updated local/parser/scope/lifecycle | 26 discovered; 21 passed, 5 explicit remote skips |
| Extracted baseline regression | 76 discovered; 70 passed, 6 fixture/platform skips |
| Modern local/remote/editor aggregate | 26 passed, 179.059 s |
| Additional installed SSH/terminal | 5 passed, 45.903 s |
| Installed actual Bash 4.4.23 editor | 8 passed, 111.509 s |
| Installed shared-search scope regressions | 5 passed, 17.039 s |
| Strengthened installed SSH → local retrieval | Exact remote command selected and successfully executed locally; passed, 20.244 s |

Runs overlap. Baseline skips are two Bash-4.4+ receivers incompatible with Mac
Bash 3.2, three Linux-hub transports and one dedicated hub import. Mac one-hop
tests supply independent SSH/import coverage; Linux aggregate results are not
Mac acceptance. The shared-search tests check the actual selected ZLE command,
including Unicode, all/auto filtering, explicit host scope and SESSION Up.
Both managed installations were updated to GLOBAL/all shells with other config
preserved. Reproduce from [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## TODO / open acceptance gates

1. Resolve native identity for identical hostname/account across different
   endpoints, including historical/imported/unregistered records.
2. Observe actual macOS and remote-editor attempted egress. Disabled networking
   configuration is established; zero-egress behavior is not measured on Mac.
3. Expand installed auth/MFA/agent/forwarding, backpressure, malformed/stale-frame,
   worker/storage/disconnect fault and concurrent-deletion coverage.
4. Broaden arbitrary zsh plugin/profile/keymap combinations, physical remote
   destinations and native import rotation/ambiguity/time-bound/scale behavior.
5. Measure startup, key-to-UI and suggestion latency separately, including
   history scaling and both local/remote delays.
6. Verify older macOS/Intel and decide signing/notarization before broader release.
   Automatic Terminal startup remains an optional future feature.

Known limits: OpenSSH 10.2's generated ProxyJump command does not quote a spaced
`-F` path; use a plain config path for jumps. Direct spaced `-F` works. Nonempty
prompt hooks/editor/debug conflicts retain GNU Readline. Exec/hard loss may leave
private remote files or terminal modes. Import alias/policy/bounds changes and
untimestamped rotations limit deduplication. Nested-shell enhancement, remote
zsh, synchronization and GUI are outside scope. See
[COMPATIBILITY.md](docs/COMPATIBILITY.md) and [OPERATIONS.md](docs/OPERATIONS.md).
