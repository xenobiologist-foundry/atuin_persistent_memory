# Continuation handoff — 2026-10-23

Read `ATUIN_SSH_CODEX_PROMPT.md` in full before continuing. It remains the
authoritative brief. The repository began empty except for that file; no
applicable ancestor/repository AGENTS.md was found. Work is in the native
Windows checkout; every Python/Bash/native execution was inside Linux Docker
containers. No separately managed WSL distribution or Windows Python was used.

## Immediate external blocker

During the final locked native build, Docker containerd failed writing
`io.containerd.snapshotter.v1.overlayfs/metadata.db` with an I/O error. Docker
Desktop subsequently reported that it could not start. Read-only diagnosis
found approximately 20 KiB free on `B:` and Docker's setting
`CustomWslDistroDir=B:\docker_desktop_data\DockerDesktopWSL`.

The user was asked to free 15–20 GB on B: and restart Docker Desktop. No unrelated
files, images, build caches or production volumes were deleted, and no global
Docker/WSL shutdown or disk move was attempted. Other host drives have space,
but choosing unrelated files to remove or relocating the user's Docker disk
requires their decision. Continue container verification once Docker is healthy.

## What actually passed

- The earlier installed production hub image ran Python 3.14.2, Bash 5.2.15,
  OpenSSH 9.2p1, official static Atuin 18.24.1, non-root SSH login and persistent
  local state. GNU Atuin was rejected by a real glibc probe and replaced by the
  checksum-pinned official musl release.
- Eight real two-hop tests passed together: Ctrl-R/Up native UI, Tab insertion,
  Enter acceptance, exact Unicode buffer/cursor/mark cancellation, immediate
  query type-ahead, foreground raw `read`, resize, remote context and hub return.
  Records were deliberately seeded through native CLI to separate this proof
  from capture. This was beyond hub-only Atuin, but was an earlier source image.
- Expanded tests established 14 of 15 cases across their runs, including
  multiline/trailing-newline selection, editing/completion/undo, custom bindings,
  vi-command and nested Bash passthrough. The vi-insert failure was traced to
  `vi-insertion` (invalid in Bash 5.2) and corrected to `vi-insert` in source.
  Its correction has not been rerun.
- Ten SSH/protocol component tests and eleven Python storage/privacy/import
  tests ran in Linux Python 3.14 containers. They do not replace real native
  capture or storage evidence.
- Initial version-pinned storage helper and distinct upstream-native ACCOUNT
  search binary compiled successfully in Linux Rust 1.95.0 stages. Subsequent
  helper replay/tombstone/discard/locking and long-query changes are unbuilt.
- Native Windows OpenSSH 9.5p2 reached published `127.0.0.1:22220`, entered hub
  sshd, and ran onward OpenSSH to the destination with strict trusted host keys.
  Actual interactive Windows Terminal native-key use has not been tested.
- PowerShell consistent backup stopped/resumed the fixture hub. Restoration to
  fresh `atuin-ssh-test-restore-{state,home}` volumes matched all 24 regular files
  by bytes, uid/gid and mode, and non-root native search read the restored state.
- Hub DNS resolved the disposable destination; intentional outbound HTTPS
  returned HTTP 200. This does not prove physical LAN DNS/VPN/firewall behavior.
- The 112-record, 20-sample measured baseline is in
  `artifacts/widget-baseline.json`: p95 key→native header 16.04 ms and
  Tab→remote Readline snapshot 8.85 ms. It includes both transports and test
  overhead. No 10k/100k/1m, artificial RTT or isolated relay claim follows.

## Rebuild and run next

From PowerShell in this checkout, after checking `docker version`:

```powershell
./scripts/hub.ps1 test
```

That builds installed runtime/test images, starts the independently named
`atuin-ssh-test` fixtures, runs the actual PTY/native tests, and runs the offline
strace observation probe. Do not substitute source-only mocks for these gates.
Production is the separate `atuin-ssh` Compose project. Never use `down -v` or
prune unrelated images/volumes while recovering space.

Prioritize, in order:

1. Compile the final sources with locked Cargo dependencies and confirm stock
   `atuin`, `atuin-ssh-native` and `atuin-ssh-search` execute in the final image.
2. Rerun the original native-key suite: later ABORT/RELEASE protocol changes,
   custom-binding checks, vi fix, session IDs and cleanup edits were source
   reviewed after Docker failed and must not inherit old passing status.
3. Prove actual remote command capture → immediate native ACCOUNT search →
   correct native metadata/record store, including a compound nonzero command.
   Run all six real native tests in `test_storage.py`, including replay,
   tombstones, collision preservation, migration refusal and remote scopes.
4. Run immediate type-ahead at 150/300 ms with the unprivileged bounded
   ProxyCommand fixture, plus concurrent workstation history visibility.
   Each relay has a volatile ingress queue; the concurrent test may expose a
   peer-ingress visibility race before another relay's local barrier can see it.
5. Run offline network-attempt observation. Configuration disables accounts,
   sync, updates and AI bindings, and the distinct TUI omits network features;
   that is not yet a completed runtime privacy proof.
6. Continue startup/hook differential tests, output flood/byte preservation,
   signal/job-control/SSH-escape failures, native DB failures, imports and
   production recreation/restore with the final native components.
7. Measure large histories and separate relay cost and the two RTTs. Complete
   actual Windows interactive, native Linux Engine and second LAN workstation
   plus firewall-boundary manual gates.

## Important source boundaries

The native UI remains upstream Atuin; Python only owns terminal scheduling,
SSH orchestration and protocol. Destination Readline owns editing/execution.
Native writes use upstream APIs, never raw SQL mutation of native tables. The
separate adapter refuses unsupported versions or migration checksums before
native writable constructors. Full build pins are `config/build-pins.toml`;
Debian security packages are resolved at build time, with a full image manifest,
so full OS byte-for-byte reproducibility is not claimed.

The in-memory login bootstrap preserves normal login profiles in the child
Bash, but the sshd command-launching shell can source a noninteractive `.bashrc`
first. A profile replacing inherited PROMPT_COMMAND can suppress bootstrap.
Existing incompatible DEBUG traps/functrace are preserved with capture degraded.
These are unresolved startup/hook MVP parity gaps, not successful fallbacks.
Different machines with the same hostname still need an explicit verified
identity mapping strategy; never fabricate hostnames to conceal account scope
or claim native hostname matching solves machine identity.

Nested sudo/su/SSH/container/tmux shells remain pass-through scopes. No remote
profile or installed file is changed by the bootstrap. The extended no-install
inventory test still needs execution. Severe interleaving inside control frames
needs adversarial recovery evidence. Current source uses bounded output
backpressure, nonce/request IDs, a type-ahead fence, ABORT cancellation and
RELEASE ownership acknowledgement; those last recovery additions are untested.

Capture timestamps come from remote EPOCHREALTIME; duration is a wall-clock
difference, not monotonic. Unknown completion remains unknown. Native uniqueness
collisions are pending, not counted as success. Import cannot reconstruct
ambiguous untimestamped multiline files or historical unknown metadata.

See `docs/STATUS.md`, `docs/COMPATIBILITY.md`, `docs/PROTOCOL.md`, and
`native-helper/README.md` for finer-grained evidence and limitations. The full
requested MVP is not complete.
