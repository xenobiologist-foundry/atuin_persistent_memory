# Delivery status

Updated 2026-10-23. This checklist records evidence, not intended capabilities.
The requested MVP remains incomplete until its defining native-key two-hop gate
and all remaining scope/capture/storage/deployment gates pass.

| Delivery item | State | Evidence or next concrete action |
| --- | --- | --- |
| Authoritative brief and repository inspection | Complete | Empty repository plus brief inspected; implementation started in place |
| Linux Python execution from PowerShell | Passed | Disposable `python:3.14.0-slim-trixie` ran SSH argv tests: 3 passed; real OpenSSH test skipped because that base lacks ssh |
| Initial foundation image | Corrected; previously running | GNU binary ABI failure corrected using checksum-pinned static musl Atuin 18.24.1; ordinary hub and destination sshd were healthy before Docker storage failure |
| SSH invocation classification | Passed component gate | Original argv preserved; special forms bypass; actual OpenSSH `-G` custom config tests pass |
| Framed protocol | Passed component gate on earlier source | Six actual Python 3.14 Linux tests cover fragmentation, unrelated escape sequences, malformed/stale/truncated/oversized data and selected command encoding; later recovery changes need rerun |
| Real native Atuin two-hop interaction | Initial vertical slice passed on earlier source | Eight PTY acceptance tests passed together in 9.835 s against installed hub package; native CLI seeds separate this gate from capture; later ABORT/RELEASE ownership recovery changes have not been built or retested |
| Input/cursor/mark, insert, accept, cancel, Up, type-ahead | Passed initial local Docker cases | Native Atuin 18.24.1, independent remote Readline snapshots, Unicode cursor/mark cancellation, Tab insertion, Enter execution, Up-specific SESSION scope, immediate activation+query, foreground raw read and resize |
| Expanded editing/keymap/nested cases | 14/15 earlier-image cases passed; source fix unverified | Unicode partial query, multiline/trailing LF selection, vi-command slash cancellation, custom binding, paste/undo/completion and nested Bash pass; Bash 5.2 rejects `vi-insertion`; source changed to `vi-insert` but image rerun is blocked |
| Delayed destination type-ahead | Implemented; blocked from execution | Unprivileged bounded hub-side ProxyCommand adds 150/300 ms destination RTT; Docker engine write failure prevented completed run |
| Remote account/directory/workspace search scopes | Extension implemented; runtime unverified, blocks MVP | Stock host scope spans users, directory is path-only, workspace discovery is hub-local; isolated pinned native extension adds exact scopes, final build/run was interrupted |
| Command capture and durable native records | Implemented; end-to-end unverified, blocks MVP | Native adapter first compile passed; component outbox tests passed separately; actual remote capture, native completion, exact replay and record integrity require final image run |
| Concurrent workstation sharing | Test implemented; unverified | Two simultaneous workstation → hub → destination sessions must immediately share native ACCOUNT history; a common local store alone does not establish the visibility barrier |
| Import/provenance/collisions | Implemented; native/end-to-end proof unverified, blocks MVP | Timestamped multiline parsing, occurrence ledger, bounded reader, dry-run, recovery and native collision preservation; eleven Python storage/import tests passed; final real-native probes require Docker recovery |
| Runtime no-account/no-external-traffic observation | Unverified, blocks MVP | Configuration alone is insufficient; capture attempted network requests during actual operations |
| Persistence and backup/restore | Passed earlier-image stopped-hub restore gate | PowerShell backup stopped/resumed fixture and wrote `artifacts/backup-check/hub.tar.gz`; fresh `atuin-ssh-test-restore-{state,home}` volumes restored all 24 regular files with exact bytes, uid/gid and modes; non-root native search read restored state; final native-extension image needs rerun |
| Windows OpenSSH | Noninteractive published-port hop passed; interactive manual gate | Native Windows OpenSSH 9.5p2 → 127.0.0.1:22220 hub → destination printed `WINDOWS_NATIVE_TWO_HOP_OK` with strict trusted host keys; actual Windows Terminal interactive keys remain unverified |
| Native Linux Docker Engine smoke | Manual gate | Same image/Compose, SSH, persistence, networking and restore |
| Second LAN workstation / firewall boundary | Manual gate | Authorized second-machine connection and outside-boundary rejection |
| Initial small-history latency | Measured on earlier image | 20 samples, 112 records, i7-14700K, amd64: key→native header p50/p95/p99 = 14.32/16.04/18.63 ms; Tab→Readline snapshot = 5.93/8.85/12.05 ms; includes both transports/test client, no isolated relay overhead |
| RTT and 10k/100k/1m performance | Unverified | Small-history baseline does not establish scaling, query/navigation or added relay latency targets |
| Docker Desktop test engine | Blocked: host B: storage full | New client container creation failed writing containerd snapshotter metadata.db with input/output error; host B: had about 20 KiB free and engine stopped; no production resources deleted |

Next action: restore Docker engine health, rebuild the corrected vi-insert/native
adapter image, then prove real capture/exact scopes and 150/300 ms type-ahead.
The latest ABORT/RELEASE recovery protocol and native replay/locking changes also
require a full rebuild and acceptance rerun; earlier evidence does not establish
that final source's behavior.
