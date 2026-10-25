# Linux hub status and TODO

Evidence recorded 2026-10-24. The installed workstation → hub → destination
interaction works. Full acceptance remains incomplete at the gates below.
Documentation cleanup does not constitute a new runtime acceptance run.

## Verified feature set

- Persistent non-root Bash hub with native Atuin, hub inline suggestions and
  local named-volume storage; installed runtime works without the checkout.
- Real onward OpenSSH, destination-authoritative editing, native Up/Ctrl-R,
  insert/accept/cancel, Unicode/cursor/mark, vi/emacs and burst-input ownership.
- Temporary destination ble.sh with exact-account suggestions, remote completion,
  foreground read/password isolation and normal cleanup; GNU Readline fallback.
- Bash 5.2 and explicit Bash 4.4.23 on a `/bin/sh` account; no destination Python
  or Atuin. Native host/account/session/path/workspace/global scopes.
- Capture lifecycle, immediate concurrent-session visibility, native records,
  privacy-before-payload, stable replay, tombstones and pending collision handling.
- Configured-HISTFILE import, repeated occurrences, multiline/timestamps,
  bounded native batches, interruption and explicit stable-ID resume.
- Byte-preserving relay, >3 MiB background-output backpressure, active-UI resize,
  jobs, less/nano/top, external editor, forwarding/ProxyJump/ControlMaster cases.
- Recreation retains native/SSH identity and home. Stopped-hub backup restored
  22 files with matching bytes/ownership/modes and native record verification.

## Recorded acceptance

| Run | Result |
| --- | --- |
| Installed modern aggregate | 177 cases, 236.151 s; 168 passed, 9 optional/dedicated skips |
| Installed actual Bash 4.4.23 aggregate | 177 cases, 246.467 s; 176 passed, 1 dedicated-import skip |
| Independent non-root SSH import CLI | Passed, 2.716 s |
| Dedicated temporary-editor two-hop suite | 7 passed on each Bash 5.2 and 4.4.23 fixture |
| Offline attempted-egress observation | 17 native + 3 hub-editor cases; zero observed Internet connect/send attempts; remote editor not separately observed |

The broad baseline uses GNU Readline; dedicated tests exercise ble.sh. Counts
overlap and do not establish full editor parity. An earlier native Windows
OpenSSH noninteractive published-port hop passed; it does not establish current
interactive Windows Terminal acceptance. Native Linux Engine remains unverified.
Versions/fixture commands: [COMPATIBILITY.md](COMPATIBILITY.md).
Measured latency/scale and six metadata-only reports: [BENCHMARKS.md](BENCHMARKS.md).

## TODO / open acceptance gates

1. Resolve native identity for different machines reporting identical
   hostname/account, including historical/imported/unregistered rows. Existing
   registered-endpoint guards do not provide full isolation.
2. Broaden profile/preexec/EXIT/existing-Atuin composition, custom keymaps,
   foreground application and OpenSSH escape/suspension parity.
3. Expand password/keyboard-interactive/agent/cert authentication and combined
   proxy/forwarding cases; keep ordinary unsupported invocation pass-through.
4. Exercise severe interleaved/malformed/stale frames, worker/relay failures,
   disconnects on both links, DB busy/full/corruption and concurrent deletion.
5. Broaden import truncation/rotation/overlap/time-bound/ambiguity and large-scale
   recovery tests. Alias/policy/bounds changes currently limit deduplication.
6. Run current interactive Windows Terminal, native Linux Engine
   network/persistence/restore, second physical LAN client/firewall rejection,
   and deliberate LAN DNS/VPN diagnostics.
7. Observe remote-editor egress; verify native daemon/pty-proxy coexistence before
   enabling them. Neither is claimed supported by the writer.
8. Measure true cold-cache/full two-hop scaling, concurrent widgets and separate
   workstation/hub latency. Native 1M query cost is a measured scaling limit.

Nested inner-shell enhancement, independent-hub synchronization and arm64 Linux
are outside current scope. Runtime fallbacks and import/privacy loss boundaries
are documented in [OPERATIONS.md](OPERATIONS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
