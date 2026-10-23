# Continuation handoff — 2026-10-24

Read `ATUIN_SSH_CODEX_PROMPT.md` in full before continuing. It remains the
authoritative brief. The repository began empty except for that file; no
applicable ancestor/repository AGENTS.md was found. Work is in native Windows.
Every Python, Bash and Rust execution was inside Linux containers; no Windows
Python or separately managed WSL distribution was used.

## Current result

The defining workstation → hub sshd → onward OpenSSH → destination Bash path
works. Destination Up/Ctrl-R opens the actual hub-local native Atuin TUI and
returns insert/accept/cancel to the same authoritative remote Readline editor.
The destination fixture has neither Python nor Atuin and receives only the
temporary in-memory Bash integration, with no installed project files.

The native PowerShell `./scripts/hub.ps1 test` completed successfully: 109 cases
in 174.546 seconds, with one intentionally skipped dedicated import case. That
case passed in the runner's separate non-root SSH import phase (1 case,
3.065 seconds). All 108 main-suite cases that ran passed. The lifecycle ran 14
offline strace privacy cases with zero attempted AF_INET/AF_INET6 connect/send
operations. This includes strict historical outcome filtering, identity
safeguards, nine foreground/terminal cases and six real SSH compatibility cases.

Docker Desktop is healthy after the user freed space and restarted it. The
earlier B: full condition is resolved. No unrelated images, caches, files or
production volumes were deleted by this project. Avoid global prune or
`down -v`; routine operations preserve named volumes.

## Evidence established

- Installed Linux/amd64 runtime: Python 3.14.2, Bash 5.2.15, OpenSSH 9.2p1,
  stock official static musl Atuin 18.24.1, plus separately named pinned native
  storage/search components. The GNU release's Bookworm glibc incompatibility
  was found by execution and corrected. The runtime needs no checkout.
  Debian packages are resolved at build time, with an installed manifest;
  full OS byte-for-byte reproducibility is not claimed.
- Native ACCOUNT/HOST/SESSION/GLOBAL and qualified remote directory/workspace;
  exact Unicode/cursor/mark cancellation, native insert/accept, vi modes,
  disabled/custom bindings, >16 KiB multiline selections and trailing newlines.
  Private protocol-2 result tags preserve literal action-prefix command text.
- Immediate activation/query/Enter and activation/query/Up/Tab bursts pass.
  Native READY delays input until negotiation, first query and results draw.
  Artificial 150/300 ms destination RTT preserves ownership and selection.
- One-entry compound capture, nonzero status, repeats, aliases, functions,
  pipelines, loops, substitutions, heredocs, history expansion, pre-command
  cwd, background launch, canceled input, foreground `read -e`, and native
  unknown completion for exit/exec. Two workstation sessions immediately
  share native history through a bounded prompt visibility barrier.
- Native stable-ID replay, tombstones, missing-view reconstruction, record
  integrity, concurrent writers, uniqueness collision retention, migration
  refusal, filter-before-durable-payload and inherited memfd query transport.
- Non-root import CLI: configured HISTFILE, dry-run, repeats, append, overlap/
  rotation, timestamped multiline/Unicode, unknown fields and read-only failure
  followed by explicit resume. Stock native records verify afterward.
- Every byte value and unrelated OSC/DCS match plain OpenSSH. Backpressure
  preserves 40,000 ordered background lines (>3 MiB) during TUI. Ctrl-Z/fg,
  Ctrl-C/cat EOF, external editor, less/nano/top, password/confirmation input
  and real login Bash pass. The flood fixture triggers its producer after the
  native UI header instead of assuming a fixed prompt delay. Corrupt REQUEST
  exercises the 30-second ABORT path; UI termination restores modes/editor.
- Recreation preserved native IDs/local key/sshd key/home marker. PowerShell
  stopped-hub backup and fresh-volume restore matched 22 regular files by
  bytes, uid/gid/mode. Stock native search/store verification passed. The
  original writer was stopped before activating the restored clone.
- Windows OpenSSH 9.5p2 → published 127.0.0.1:22220 → hub → destination printed
  `WINDOWS_NATIVE_TWO_HOP_FINAL_OK` with strict trusted keys. Docker Desktop
  4.58, Engine 29.1.5 and Compose 5.0.1 supplied Linux containers.
  Interactive Windows Terminal remains a manual gate.

## Performance

See `docs/BENCHMARKS.md` and metadata-only JSON in `artifacts/`.

The final two-hop widget baseline uses 20 samples/994 native rows:
Ctrl-R → native header p50/p95/p99 = 21.98/27.21/29.49 ms; Tab → independent
remote snapshot = 6.64/8.25/9.20 ms. It includes transports/client overhead.
A 1,000-sample raw-cat differential measures about 0.20 ms p95 extra round-trip
cost for the relay path, not isolated one-way latency.

Native real-PTY tests use 10k/100k/1m rows, 20 samples/action. Warm-OS-cache
first-results p95 is about 10–14 ms. A narrowed query key plus Tab/process exit
p95 is 7.38/23.09/213.49 ms; 1m query cost is a measured scaling limit. The 100k
conservative upper bound meets the 50 ms target. Seeds use native APIs and
encrypted records, never raw SQL native writes; the seed binary is absent from
production. Reconciliation scans native encrypted records: measured 1m recovery
takes about 11.2 seconds, with a bounded 120-second background-only allowance.

## Remaining MVP gates

The full requested MVP is not complete. STATUS/COMPATIBILITY distinguish
passed evidence, known failures, conservative fallback and manual gates.

- Native history lacks verified machine identity beyond reported hostname.
  Connection provenance retains aliases/effective endpoints/real origins.
  Distinct endpoints with the same hostname/account need explicit mapping.
  Safeguards hold allowed affected captures pending and refuse misleading
  exact-account search; both policies and registry corruption passed actual
  native tests. Stock and
  historical unregistered sessions are outside this endpoint-conflict detector.
  Full import/search identity isolation needs a native-compatible design.
- The real login child preserves profiles, but sshd's command-launching Bash
  can run noninteractive .bashrc first. Descriptor initialization loads login
  profiles before composing their final PROMPT_COMMAND, including replacements.
  Original POSIX startup or unsupported descriptor/ENV cases stay plain.
  Incompatible DEBUG/functrace are preserved;
  enhanced keys/capture degrade because foreground eligibility is unproven.
  Complete preexec/EXIT/existing-Atuin startup parity remains work.
- Basic HISTIGNORE globs and exact & are supported without policy changes.
  Complex escaped/bracket/extended/embedded-& repeat patterns conservatively
  suppress duplicate fallback capture with a degradation notice.
- With store_failed=false, at most 128 commands/16 MiB stay in RAM until
  successful completion. Failed/unknown outcomes never become durable bodies.
  Incomplete commands can be lost on process/transport loss. Unknown imported
  outcomes remain pending without local payload, requiring explicit policy
  change plus refetch, never fabricated success.
- Native daemon operation is refused until verified. Experimental pty-proxy
  coexistence beyond recursion bypass is unverified. Stock Atuin stays usable.
  No account/sync/telemetry/AI/history service is provisioned; intentional
  SSH/curl/Git networking remains usable.
- Nested sudo/su/SSH/container/tmux shells pass through; only the outer launch
  is captured. No inner identity is guessed from visible prompts.
- Physical second LAN workstation/firewall rejection, LAN DNS/VPN, native
  Linux Engine network/persistence/restore and interactive Windows Terminal
  need actual execution. Only linux/amd64 has evidence.
- True cold-cache, full two-hop scaling and separate workstation/hub delay
  remain performance gates; 50/150/300 ms destination-delay correctness passes.
- Broader concurrent deletion, disk-full/transport disconnect, authentication/
  escape combinations and hostile frame interleaving remain in the matrix.
  Do not replace these contracts with unit-test counts.

## Continue

From native PowerShell:

```powershell
./scripts/hub.ps1 test
```

This builds installed images, starts `atuin-ssh-test`, runs PTY/native tests,
observes attempted offline traffic, and runs the independent non-root
`atuin-ssh-import-check` phase. Test resources are separate from production
`atuin-ssh`. Import cleanup removes only its containers/network, preserving
volumes. Use `./scripts/hub.ps1 test-import` for that phase alone.

Use README's public-key quickstart for production. Never attach personal history
to tests/benchmarks. Keep Linux execution in containers, preserve unrelated work,
update evidence after source changes and make reviewable commits. Complete
identity/startup parity and manual host/LAN gates before declaring full MVP.
