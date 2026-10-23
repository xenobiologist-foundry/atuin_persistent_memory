# Delivery status

Updated 2026-10-24. This checklist records evidence, not intended capabilities.
The defining native-key two-hop interaction works in the installed container.
The brief's complete MVP remains incomplete while the parity and deployment
gates below remain open.

| Delivery item | State | Evidence or next concrete action |
| --- | --- | --- |
| Authoritative brief and repository inspection | Complete | Empty repository plus brief inspected; implementation started in place |
| Linux Python execution from PowerShell | Passed | Final installed-image suite ran Python 3.14.2/Bash/OpenSSH in Linux containers from native PowerShell; no Windows Python or separately managed WSL distribution required |
| Foundation image | Passed installed image gate | Checksum-pinned static musl Atuin 18.24.1, Python 3.14.2, Bash 5.2.15 and OpenSSH 9.2p1 on Debian 12; installed package works without checkout; ble.sh is bundled for hub inline suggestions |
| SSH invocation classification | Passed component gate | Original argv preserved; special forms bypass; actual OpenSSH `-G` custom config tests pass |
| Actual SSH compatibility | Six installed-image cases passed | Real aliases, configured RemoteCommand, explicit command and status, TCP forwarding, ProxyJump and shared ControlMaster ownership passed in 10.335 s; further authentication and escape coverage remains |
| Framed protocol | Passed component gate | Fragmentation, unrelated escape sequences, malformed/stale/truncated/oversized data, response chunking, ABORT/RELEASE recovery and actual terminal-query handling exercised in the aggregate suite |
| Real native Atuin two-hop interaction | Defining interaction demonstrated | Real workstation SSH → installed hub → Python-free destination Bash; native ACCOUNT UI, Tab insert, Enter accept, Escape cancellation, Unicode cursor/mark preservation, vi insert/command and native Up-specific scope |
| Actual destination shell compatibility | Automated modern/legacy gates passed; physical legacy retest pending | Bash 5.2.21 destination handshake/native capture verified and Ctrl-R confirmed by user. The original `/bin/sh` account with Bash 4.4.23 stayed plain; explicit `connect --bash` now selects existing Bash 4.4+ for one session and passes the actual 4.4.23 `/bin/sh`-account fixture. No project files installed on destinations |
| Hub inline suggestions | Real SSH and full regression gates passed | Pinned ble.sh and native Atuin history source; visible ghost text, Right Arrow insertion without execution, Enter complete-command execution, native Ctrl-R/cancel pass. Default native scope is preserved; no destination editor installation |
| Hub locale follow-up | Passed focused installed-image SSH checks | Default LANG=C.UTF-8 before ble.sh when unset/empty; explicit LANG/LC_* preserved. Four actual SSH tests passed in 7.226 s, including native suggestions and Ctrl-R/cancel. Normal first-use tput cache generation retained |
| Startup ownership/type-ahead | Passed focused real PTY gates | Native READY descriptor after negotiation/first query/first frame prevents early input loss; Ctrl-R + query + Enter and Ctrl-R + query + Up + Tab in one write pass, including selection of an older matching command |
| Editing, output and jobs | Passed installed-image PTY gates | Exact >16 KiB Unicode/quotes/tabs/trailing-newline selection; plain-OpenSSH differential for every byte value and unrelated OSC/DCS; 40,000 ordered background lines (>3 MiB) survive bounded buffering; Ctrl-Z/fg/Ctrl-C/cat EOF, external editor, nested Bash, less/nano/top and password/confirmation input; active-UI resize preserves selection and reaches remote stty |
| Delayed destination type-ahead | Passed 50/150/300 ms scenarios | Unprivileged bounded hub-side ProxyCommand adds half the stated RTT in each encrypted-stream direction; immediate Ctrl-R/query reaches the widget and selection returns to the same remote editor; no workstation/hub delay injected |
| Remote account/directory/workspace search scopes | Native extension exercised | Distinct pinned `atuin-ssh-search` retains upstream TUI, adds exact ACCOUNT and qualified directory/workspace scopes; actual native tests distinguish host/account/global/path/workspace; no schema changes |
| Command capture and native records | Passed installed-image aggregate gate | Fifteen real two-hop lifecycle cases cover pipelines/functions/loops/substitution, shell status, repeated commands, cancellation, background launch, cwd, aliases/provenance, interactive read, HISTIGNORE/leading space, heredoc, history expansion and unknown exit/exec completion |
| Concurrent workstation sharing | Passed actual two-session gate | Two simultaneous workstation → hub → destination sessions immediately share ACCOUNT history through the hub's native store after prompt visibility/barrier fixes |
| Import/provenance/collisions | Native/component and actual SSH probes passed; remaining parity listed below | Bounded raw-PTY Bash reader, timestamped multiline parsing, occurrence ledger, count-only progress, dry-run, bounded native batches, SIGINT/explicit-resume stable-ID verification and serialized coordinators; broader rotation/time-bound/ambiguity coverage remains incomplete |
| Runtime no-account/no-external-traffic observation | Passed 20 offline observations | `strace` under `--network none` detected zero attempted Internet requests: 17 stock/native startup, capture, search, batch/import/check and real TUI cases plus 3 actual ble.sh startup/suggestion/refused-update cases |
| Persistence and backup/restore | Passed installed-image operations gate | Forced recreation preserved native record/local key/sshd key/home fingerprints; PowerShell stopped-hub backup and fresh-volume restore compared 22 regular files byte-for-byte with uid/gid/modes; non-root native search and store verification passed; source stopped before activating restored writer |
| Windows OpenSSH | Earlier noninteractive published-port hop passed; current-image/manual gate | Native Windows OpenSSH 9.5p2/LibreSSL 3.8.2 → published localhost hub → destination printed `WINDOWS_NATIVE_TWO_HOP_FINAL_OK` with strict trusted host keys. Repeating it for the inline-suggestion image was not run: automatic approval review rejected exporting its disposable private fixture key onto Windows. Actual Windows Terminal interactive keys remain unverified |
| Native Linux Docker Engine smoke | Manual gate | Same image/Compose, SSH, persistence, networking and restore |
| Second LAN workstation / firewall boundary | Manual gate | Authorized second-machine connection and outside-boundary rejection |
| Small-history two-hop latency | Measured installed protocol-2 image | 20 samples, 994 records, i7-14700K, amd64: key→native header p50/p95/p99 = 21.98/27.21/29.49 ms; Tab→Readline snapshot = 6.64/8.25/9.20 ms; includes both transports/test client |
| Native 10k/100k/1m performance | Measured independently of SSH/relay | 20 samples/action/size; exact first-results READY and verified query/navigation selections; native first-results p95 about 10–14 ms; single-query-key plus Tab/exit p95 7.38/23.09/213.49 ms; warm OS cache; see COMPATIBILITY and raw report |
| Relay overhead comparison | Measured real two-hop differential | 1,000 exact 32-byte raw-cat echoes per path, after 20 warmups: plain/enhanced round-trip p95 0.689/0.889 ms; difference about 0.20 ms supports local 5 ms target, but does not isolate one-way relay latency |
| Remaining performance gates | Unverified | Full two-hop scaling, true cold-disk behavior and separate workstation/hub latency; native 1M query cost is a measured scaling limit |
| Docker Desktop test engine | Recovered | Host B: exhaustion interrupted an earlier build; space was freed and Docker restarted, followed by successful installed-image builds/tests; no production resources were deleted by this project |
| Compatibility/import regression | Passed installed modern and legacy images | Modern: 148 cases in 138.054 s, OK with 9 skips (8 optional legacy probes and dedicated import). Bash 4.4.23 fixture: 148 cases in 148.495 s, OK with only the dedicated-import skip. Independent non-root SSH import CLI case passed in 2.665 s. No production history was used |
| Last full aggregate before locale follow-up | Passed installed modern and legacy images | Modern: 150 cases in 173.164 s, OK with 9 skips. Bash 4.4.23 fixture: 150 cases in 186.773 s, OK with only the dedicated-import skip. Includes real hub ghost-text/acceptance/cancel and complete onward SSH regression. Known fixture prompt/WAL access races corrected; no runtime workaround or skipped failure |
| Native import throughput | Measured 200-entry fixture | Individual helper calls 7.9936 s; bounded batches 0.4599 s on this host, with native row/record verification. SSH and ledger alignment excluded; uncertain writes still reconcile individually |

Next action: implement explicit machine mapping, broaden startup/hook and storage
compatibility, and complete the physical-platform/LAN/manual parity gates before
claiming full MVP.

## Remaining parity gates

Every unverified item below blocks claiming the brief's complete MVP. These are
not established failures unless explicitly identified as a known gap.

| Area | Remaining evidence or known gap |
| --- | --- |
| Final native key contract | Explicit insert-result tagging, activation bursts, literal action-prefix commands, active-UI resize and strict privacy cases pass the final aggregate; full custom keymap coverage remains |
| Startup/hook parity | Descriptor bootstrap composes the final scalar/array PROMPT_COMMAND before its first execution; profile replacement no longer suppresses installation. POSIX/readonly ENV/unavailable descriptor cases stay plain; incompatible DEBUG/functrace disables enhancement and capture. EXIT/preexec/existing-Atuin combinations need broader evidence |
| Shell editing and applications | Existing tests cover multiline selection, >16 KiB bounds, external editor, cat/read, Ctrl-C/Z/D, fg, heredocs, history expansion, less/nano/top and password/confirmation; Vim, further REPLs and OpenSSH suspension/escapes need additional evidence |
| Native SSH compatibility | Six real cases pass aliases, configured RemoteCommand, explicit command/status, TCP forwarding, ProxyJump and shared ControlMaster ownership. Combined flags and further proxy/forwarding combinations, password/keyboard-interactive/agent/cert authentication and escape behavior remain |
| Output and recovery | Byte differential, >3 MiB backpressure and terminal queries pass; continue broader malformed/interleaved-frame, stale-generation, worker/relay failure and both-transport disconnect faults |
| Capture lifecycle | Fifteen lifecycle cases pass the recorded aggregate, including status, expanded history and unknown exit/exec completion; broader interrupt/disconnect and history-policy combinations remain. Complex HISTIGNORE patterns conservatively fall back for duplicate capture; they must not bypass privacy |
| Context and native scopes | Exact native scopes pass fixture probes. Conflicting registered endpoints for one reported origin cause pending live capture and refused ACCOUNT selection. Direct-native reproduction confirms the representation gap; imported/unregistered history and preexisting rows remain outside the guard and can overlap. A mapping solution is required |
| Storage and privacy | Stable-ID crash-window replay, deletion/tombstones, native uniqueness collisions, concurrent writers and privacy-before-durable-payload cases pass; broader concurrent deletion, DB busy/read-only/full/corruption and daemon capability remain |
| Imports | Native/ledger probes and actual SSH CLI custom-HISTFILE append/rotation/read-only recovery pass; broader truncation/overlap, ambiguity, time bounds, large imports and interrupted resumability remain |
| Central sharing | Containerized concurrent-workstation immediate visibility passes; physical second-workstation/LAN firewall boundaries remain manual; independent hubs remain separate, with no cloned concurrent writer identities |
| Deployment and privacy | Installed image, no-install destination inventory, recreation/restore and final offline attempted-egress tests pass; deliberate LAN DNS/HTTPS/VPN diagnostics remain |
| Actual host/LAN/platform tests | Interactive Windows Terminal keys, native Linux Engine image/network/persistence/restore, second authorized LAN workstation and boundary rejection, LAN IP/DNS and VPN diagnostics |
| Performance | Native 10k/100k/1m, small-history two-hop and real relay differential measured; 50/150/300 ms destination-delay correctness passes; true cold-cache, full two-hop scaling and independent workstation/hub delay remain unverified |

Nested inner shells deliberately remain usable pass-through scopes, with no
claimed inner capture/enhancement. This documented boundary follows the brief;
its complete foreground-application behavior still needs the tests above.
The implemented image targets linux/amd64. Arm64 is outside this delivery scope.
