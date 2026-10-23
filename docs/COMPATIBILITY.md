# Compatibility evidence

Updated 2026-10-23. A source observation, a component test, and a working two-hop
terminal test establish different things. Only the last establishes onward
native-key integration. See [STATUS.md](STATUS.md) for actual current results.

The workstation is a terminal/OpenSSH client. The hub owns the installed native
Atuin and its local persistent state. The destination owns Bash's authoritative
Readline buffer; its integration consists of session-only Bash functions.

## Reproduce the probes

All Python and Bash execution belongs in Linux containers. From native Windows
PowerShell or Linux, use:

```text
docker compose -f compose.test.yaml build
docker compose -f compose.test.yaml up -d --wait hub destination
docker compose -f compose.test.yaml run --rm client
docker compose -f compose.test.yaml down
```

The test project has independent keys and volumes. `down` preserves them. The
client runs the installed build and exercises real workstation → hub →
destination OpenSSH PTYs. `tests/test_two_hop.py` verifies insertion with an
independent Readline snapshot binding, acceptance by observing the selected
command's output, cancellation by comparing the original buffer/cursor/mark,
immediate type-ahead, Up, foreground `read`, context and resizing.

Native interface probes can run without opening any production state:

```text
docker run --rm --entrypoint /bin/bash atuin-ssh:local -c 'atuin --version; bash --version; ssh -V; python --version'
docker run --rm --entrypoint atuin atuin-ssh:local init bash
docker run --rm --entrypoint atuin atuin-ssh:local search --help
docker run --rm --entrypoint atuin atuin-ssh:local history start --help
docker run --rm --entrypoint atuin atuin-ssh:local history end --help
docker run --rm --entrypoint atuin atuin-ssh:local pty-proxy --help
```

For manual TUI probes, start an interactive disposable container with an empty
`ATUIN_HOME`. Native `history start/end` seed its state, `search -i --result-file`
captures exact result bytes, and `od -An -tx1` exposes the difference between an
inserted command, an accepted command and cancellation. A normal search result
is command text; an acceptance result begins `__atuin_accept__:`. The exact
result-file path avoids command substitution's trailing-newline removal.

## Pinned source findings and implications

The reviewed [v18.24.1 search entry point](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin/src/command/client/search.rs)
supports `ATUIN_QUERY` and exact `--result-file` output. Author and shell filters
are passed to the noninteractive branch; they do not provide an exact-account
restriction for the TUI. [The native TUI](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin/src/command/client/search/interactive.rs)
owns action/keymap handling and the acceptance prefix.

[Native database context](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-client/src/database.rs)
uses the environment session and command origin, obtains cwd, and discovers Git
from the local filesystem. Native host matching deliberately includes users on
the same hostname; directory matching does not qualify by host/account. Setting
a remote `PWD` cannot establish its Git workspace. The bridge must disclose
stock host scope and disable local workspace inference until a verified native
extension supplies the required exact scopes. A fake hostname or copied Python
search UI is not a compatibility fix.

The installed generated Bash integration must be checked after every pinned
version change. Its modern acceptance mechanism dispatches Readline macros: a
`bind -x` callback inserts the selected buffer, then a second reserved macro
conditionally invokes Readline `accept-line`. This permits real Bash parsing
and execution. The bridge must never `eval` a returned command.

## Capability matrix

| Surface | Required proof | Current boundary |
| --- | --- | --- |
| Native insert/accept/cancel | Real TUI and remote Readline snapshot | Automated test implemented; results in STATUS |
| Context overrides | Native search/list output with two hosts/accounts | `ATUIN_HOST_NAME`, `ATUIN_HOST_USER`, session, shell, PWD source reviewed; runtime verification required |
| Exact account/directory/workspace scopes | Cross-account results and global switching | Stock native TUI gap; blocks required default scope |
| Native records/privacy/replay | Record-store checks and crash-window faults | Separate version-pinned adapter required; never raw SQL writes |
| Historical import | Timestamp/multiline/occurrence/collision fixtures | Unknown fields must remain documented/pending; no fabricated historical metadata |
| Startup/hook composition | Plain-vs-enhanced differential sessions | Profiles, traps, preexec, custom options and existing Atuin need coverage |
| Experimental pty-proxy | Generated integration + coexistence session | Never enable output retention or recursive proxying; active proxy must bypass safely |
| OpenSSH invocation modes | Native `ssh -G` plus passthrough tests | Explicit commands, queries, subsystems, non-TTY, background and forwarding-only bypass |
| Terminal transport | Arbitrary bytes, frames, output flood, resize, jobs | Framing component tests plus full-session tests; failures remain MVP blockers |

Nested `sudo`, `su`, SSH, container shells and tmux/screen attachment are separate
instrumentation scopes. They must remain usable as foreground programs. Their
inner commands/context are not captured by observing their visible prompt.

## Platform evidence and failures

The first foundation image used Python 3.14.2 on Debian 12, Bash 5.2.15,
OpenSSH 9.2p1 Debian-2+deb12u10 and OpenSSL 3.0.22. Its GNU Atuin binary refused to
run because GLIBC_2.38 and GLIBC_2.39 were unavailable. This was a real failed
probe and prompted a static-musl asset correction. The corrected native binary
reports `atuin 18.24.1 (c58d2e993d05be423315f6ae3739e9ab3e45eea5)` and its real
TUI passed the initial eight-case two-hop suite. Native help and the generated
Bash macro-chain implementation were inspected in that image.
The later ABORT/RELEASE ownership-recovery protocol and native helper
replay/locking edits were made after Docker failed and remain unbuilt and
unverified. Repeat the complete suite against the final installed image.

Actual Bash 5.2 rejects `bind -m vi-insertion` as an invalid keymap. Native Atuin
uses `vi-insert`. The expanded PTY suite caught this independently: vi-command
slash worked while vi-insert Ctrl-R fell back to ordinary reverse search. A
source correction requires a rebuilt image and another passing run.

The effective pinned `ATUIN_HOME=/state/atuin` stores native state below `data/`:
`history.db`, `records.db`, `meta.db`, the local storage key, and live WAL/SHM
files. Configuration is `/state/atuin/config.toml`. Preserve the complete root
for backup, quiescing every writer first.

## Measured initial latency

Run the reproducible metadata-only benchmark in the disposable test client:

```text
docker compose -f compose.test.yaml run --rm client python tests/benchmark_pty.py --samples 20
```

The 2026-10-23 run used 20 samples and 112 native records on an Intel i7-14700K,
linux/amd64 Docker Desktop kernel 6.6.87.2, Python 3.14.2 and native Atuin 18.24.1.
Ctrl-R→native header p50/p95/p99 was 14.32/16.04/18.63 ms. Tab→remote shell redraw
plus independent Readline snapshot was 5.93/8.85/12.05 ms. The unique query was
already typed in authoritative remote Readline. These wall-clock measurements
include workstation/hub transport, the destination ownership roundtrip, native
UI work and the test client. They do not isolate relay overhead, establish
query/navigation response time or prove the 10k/100k/1m targets. No artificial
RTT was configured for this baseline.

`tests/latency_proxy.py` supplies an unprivileged, bounded OpenSSH ProxyCommand
fixture for 150/300 ms added destination RTT. It delays encrypted stream chunks
in both directions. This is distinct from complete packet/congestion emulation,
and does not affect the workstation→hub link. Completed evidence is tracked in
STATUS; writing the fixture alone does not pass the latency acceptance gate.

Actual native Windows Terminal/OpenSSH, a second LAN workstation, native Linux
Docker Engine and arm64 execution require separate recorded runs. A Linux
container test launched from PowerShell does not prove all of those surfaces.
Native Windows OpenSSH 9.5p2 did complete a noninteractive strict-host-key-checked
published-port hub → destination command. The earlier-image stopped-hub backup
was restored into fresh test volumes: 24 regular files matched byte content,
ownership and modes, and non-root native Atuin search read the restored state.
Those results do not establish interactive Windows terminal behavior or the
final native-extension image's restore compatibility.
