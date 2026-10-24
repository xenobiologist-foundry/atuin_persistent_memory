# Continuation handoff — 2026-10-24

Read `ATUIN_SSH_CODEX_PROMPT.md` in full before continuing. It remains the
authoritative brief. The repository began empty except for that file; no
applicable ancestor/repository AGENTS.md was found. Work is in native Windows.
Every Python, Bash and Rust execution was inside Linux containers; no Windows
Python or separately managed WSL distribution was used.

## Current result

The defining workstation → hub sshd → onward OpenSSH → destination Bash path
works. Destination Up/Ctrl-R opens the actual hub-local native Atuin TUI and
returns insert/accept/cancel to the authoritative destination editor.
The destination fixture has neither Python nor Atuin. GNU Readline mode uses
only in-memory Bash integration. The user's later editor extension also loads
a private temporary ble.sh tree, with no permanent installation or profile edits.

The compatibility/import correction is committed as `dfcb8c2`. With the initial
hub inline editor, the earlier installed modern-image suite passed 150 cases in
173.164 seconds with 9 skips (8 optional legacy probes and the dedicated import
case). The actual GNU Bash 4.4.23 fixture passed 150 cases in 186.773 seconds
with only the dedicated import skip. The independent non-root SSH import case
passed in 2.665 seconds against the corrected import code. Tests use disposable
history only. Native offline strace observation passed 17 cases; the additional
ble.sh startup/suggestion/refused-update observation passed 3 cases. Neither
observed any attempted AF_INET/AF_INET6 connect/send operations.

The hub now bundles pinned ble.sh for inline ghost text from native Atuin
history, with real SSH Right Arrow/Enter/Ctrl-R coverage. See COMPATIBILITY for
the release, full commit and archive digest. This initial editor addition was
hub-only. The later user-approved mode described below also loads a temporary
destination editor. Its update hook
refuses downloads. `ATUIN_SSH_HUB_AUTOSUGGEST=0` must be set before hub startup
to disable it. Native HOST scope is unchanged.

That earlier hub-only regression used runtime image
`sha256:9ddf5ac93a4b40a7e16bf531f880fe636dac7bf9e37ee3a7b4b6a9515ed7674d`.
Its final modern test image is
`sha256:7cfa6f68b552d5b4c3d7ec3642f6b50fa775d54e99c2cdc307629524507c0bb2`;
the corresponding legacy test image is
`sha256:1a301d963fd9638f84087106d88963d9b1e48f2c14428dd48c4a594f2f3ba2bc`.
Completed review/autocomplete/legacy fixture containers and networks were
removed; their named volumes were preserved. Production was left untouched.

A later user login exposed empty LANG under sshd. Hub initialization now supplies
`C.UTF-8` only for unset/empty LANG before loading ble.sh; client/profile LANG
and LC_* choices are preserved. The installed locale runtime is
`sha256:5099384dd20a87613d2cd755663fdd5cdd156b49ebcb2f3a856c773f8d128fcf`;
test image `sha256:d8e95093e0a352fc673ec553f8bbbe95ea08b3a612267dd3e3c4871356d9b3c3`.
Focused real SSH tests passed all 4 cases in 7.226 seconds, including missing/
empty LANG, explicit locale preservation and existing native suggestion/search
behavior. This narrow follow-up did not repeat the full aggregate or recreate
production. ble.sh's first-use tput cache completion is normal initialization.

The user then explicitly selected temporary destination ble.sh with hub-native
history after comparing it with a hub-side editor. This is an approved extension
of the original GNU Readline/functions-only contract. Packaged connections use
it by default; `--no-autosuggest` retains the earlier mode and
`ATUIN_SSH_REMOTE_AUTOSUGGEST=0` changes the hub shell's default. An explicit
`--autosuggest` overrides that setting. Native history and the real search UI
stay on the hub; completion and command execution stay on the destination.
The pinned archive is 3,799,040 bytes with SHA256
`63a0c475827efb41f8156a28b8e057749c28f03fc4cc9b5989e86b204ee945ee`.
Each connection transfers it over the existing SSH stream into a private temp
directory, checks its size/hash and loads it after profiles. No remote download
or system installation is used. Graceful BLE unload removes the session files;
`exec`, abrupt kill or power loss may leave a private temporary directory.

Existing nonempty PROMPT_COMMAND hooks, an existing editor or incompatible debug
hooks retain GNU Readline. A startup-read test covers scalar/array prompt hooks.
Seven dedicated installed two-hop editor tests passed on Bash 5.2 in 52.509 s
and Bash 4.4.23 in 50.632 s. They cover account-filtered ghost text, Right/Enter,
destination-only completion, real native insert/accept/cancel, Unicode cursor/
mark, one-write activation/query/Enter, foreground read/password ownership,
subshell lifetime and graceful cleanup. Four bundle, seven native prefix and
six relay tests cover integrity, bounds, exact text and input/generation ownership.

The current installed modern aggregate passed 177 cases in 236.151 s with
9 skips. The actual Bash 4.4.23 aggregate passed 177 cases in 246.467 s with
only the dedicated-import skip. Baseline tests explicitly use GNU Readline; the seven new editor
tests select ble.sh. Independent final-image non-root SSH import passed in
2.716 s. Final-image offline probes observed zero Internet connect/send attempts
across 17 native and 3 hub-editor cases; remote-editor egress was not separately
observed. The final runtime image is
`sha256:891e014c6748b246a80adfe01f5cfafb115bd02cb06d3e088e7c620b72bda42f`;
modern test image is
`sha256:babd4c919a889efc9094013e9ae400c65cc9f7e388891439ec8c80b1a40e67b4`;
legacy test image is
`sha256:13ba566ada9c2d3aa9153f57c4884783f5ff6a9f3e2149b9113da66b177b8f2a`.
These are Docker image inspect IDs (manifest lists on this Desktop backend).
The modern, legacy and dedicated import containers/networks were removed without
`-v`; their named volumes were preserved.

The user's running production container was deliberately left on its old image
while independent projects tested candidate tags. Do not silently recreate it
or resume the real canceled import. `docker compose up -d --build` applies the
update and disconnects active SSH sessions. After reconnecting, the user can run
`atuin-ssh history resume-imports` to continue saved work without another fetch.
The latest read-only production inspection showed image
`sha256:9f09de57be475a59df227655d1ba54bcbb5683b6f6ae871ab5b6fea94c713d9c`,
started 2026-10-23T23:03:56.559215239Z; this iteration did not recreate it.

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
- Native import setup is shared across bounded batches, retaining privacy before
  durable ledger payload and stable IDs. Count-only progress, concise exit 130,
  whole-coordinator serialization and uncertain-write reconciliation are tested.
  A fault fixture commits three records before losing a 64-entry batch reply;
  explicit resume plus six pending entries produces exactly 70 original native
  IDs/records. Literal target aliases and accepted snapshots still define import
  alignment; alias/bounds/privacy changes or ambiguous untimestamped rotations
  are not an exactly-once guarantee.
- Explicit `atuin-ssh connect --bash -- target` uses existing Bash 4.4+ even for
  `/bin/sh` accounts; Bash 4.4 needs existing fractional `date` support. Automatic
  enhancement still requires the configured Bash 5+ shell. The actual patched
  GNU 4.4.23 fixture has no Python or Atuin. Scalar prompt hooks, private keymap
  sequences, first-prompt native UI/capture and normal history defaults pass.
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
  This is evidence from an earlier image. Repeating it for the inline-suggestion
  image was not run because automatic approval review rejected copying the
  disposable fixture's private key onto Windows; no extraction retry was made.
  Current-image native Windows and interactive Windows Terminal remain gates.

## Performance

See `docs/BENCHMARKS.md` and metadata-only JSON in `artifacts/`.

A 200-entry native import fixture measured 7.9936 seconds with individual helper
processes and 0.4599 seconds with bounded batches, verifying rows and encrypted
records. This excludes SSH/ledger alignment and does not remove the individual
record reconciliation cost of uncertain prior writes.

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
