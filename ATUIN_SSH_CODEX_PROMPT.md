# Atuin SSH Shell Hub — Codex implementation prompt

Revised 2026-10-23 for native Windows development, Docker Compose deployment, and strictly local/LAN history with no Atuin account. This revision supersedes both the earlier WSL-first deployment plan and the account-based synchronization design. Treat this document as the implementation brief. The working product name is `atuin-ssh`; it is a new project, not a claim that this package already exists.

## 1. Mission and the primary acceptance gate

Build a persistent Linux shell hub packaged as a Docker image and managed with Docker Compose. I use native Windows Codex and PowerShell to develop the project in a Windows checkout. All Linux builds, Python execution, Bash execution, and automated integration tests run inside containers. Do not require a separately maintained WSL development distribution, native Windows Python, or a Windows port of Unix PTY code.

The same Linux image must run on Windows 11 Docker Desktop in Linux-container mode and on native Linux Docker Engine. This is portability through a Linux runtime; do not describe it as a native Windows executable. Docker Desktop still supplies a Linux kernel/VM backend. Use a supported stable backend without requiring the user to work inside it. Target linux/amd64 first; add linux/arm64 only with actual build and execution evidence.

The hub contains OpenSSH server/client, GNU Bash, native Atuin, the Python 3.14 middleware, and a small practical set of terminal tools. I SSH into its published port from Windows Terminal or another LAN computer and get an ordinary persistent Bash environment with native Atuin enabled. From that hub shell, I type `ssh myserver` and receive the original enhanced remote-shell experience without installing Atuin or an agent on the destination.

Use three explicit terms throughout the implementation:

- **Workstation:** the terminal/SSH client, such as Windows Terminal and Windows OpenSSH.
- **Hub:** the Linux container that runs Atuin, the bridge, and persistent local state.
- **Destination:** the machine reached by an onward SSH connection from the hub.

Here, “local Atuin” means local to the hub. Its database stays on the Docker host's local persistent storage. The workstation does not need Atuin. The destination needs ordinary SSH access and a compatible modern Bash, with no installed Atuin, Python, agent, daemon, or persistent project files.

Use Python 3.14 for the bridge core and a session-only Bash payload on destinations. Use a pinned Debian-based slim runtime with GNU Bash/OpenSSH compatibility. Atuin v18.24.1 and destination Bash 5.2 are source-reviewed starting points; verify and record the actual Python, Bash, OpenSSH, native Atuin, image digests, Docker, and Compose versions. Recheck any different version rather than assuming unchanged interfaces. Remote Python is never a requirement.

**The defining feature remains native history-key integration with the real destination shell.** At that Bash prompt, Up and Ctrl-R invoke native Atuin on the hub through the normal editing workflow. Search, insertion, acceptance, cancellation, command capture, and context must work in that same destination Readline editor. Ordinary use requires no middleware prefix, alternate search shortcut, separate search command, or second terminal.

Installing Atuin only in the hub proves the hub's own history integration; it does not satisfy onward SSH integration. Likewise, ProxyJump forwarding alone does not run the hub's shell integration. Prove the complete workstation → hub → destination interaction before expanding ancillary features.

**Hard requirement: no Atuin account and no external history services.** Do not register or log into Atuin, require an email address, create a hidden local Atuin account, enable hosted synchronization, or connect history/terminal content to an external service. All history, configuration, native record state, and bridge metadata stay on hardware controlled by the user. Ordinary SSH key authentication to the hub and destination OS accounts remain necessary and are independent of Atuin accounts.

Support two deployment layouts with the same image: a local hub on the user's computer, or a central hub on a LAN machine that the user's computers enter over SSH. In both layouts, native Atuin operates beside its own local persistent SQLite state. LAN-wide shared history comes from sessions using the same central hub, without an Atuin sync service or a database shared over a network filesystem. Separate independent hubs have independent histories; do not advertise automatic synchronization between them.

Once images and dependencies are installed, history recording/search must work with public internet access unavailable. Preserve user-requested network operations such as onward SSH to a VPS, curl, and Git; this restriction applies to background history/application services, not to commands the user intentionally runs.

Build working software, images, Compose files, setup/backup tooling, integration tests, and a handoff. Inspect the existing repository and its instructions before changing anything. Make reasonable decisions, record them, and proceed through the milestones. Do not stop after an architecture proposal.

## 2. Required interaction contract

| User action or situation | Required behavior |
| --- | --- |
| SSH from the workstation into the hub | Enter the hub's normal Bash with native Atuin already initialized and persistent history available. |
| `ssh myserver` from the hub's integrated Bash | Start normal SSH and automatically enhance a supported destination interactive Bash session. |
| Up at an eligible remote Readline prompt | Invoke the actual local Atuin widget, respecting its Up-specific configuration and normal multiline behavior. |
| Ctrl-R at that prompt | Invoke the actual local Atuin search with the current remote editing buffer as the initial query. |
| Up/Down and other navigation inside Atuin | Search and navigate on the hub; no destination or separate history-service request per query/navigation key. The workstation-to-hub terminal connection still carries input/output. |
| Tab / insert action | Return the selected command to remote Readline for editing, without executing it. |
| Enter / accept action | Follow the user's native Atuin `enter_accept` and keymap behavior; execute only when that native action requests execution. |
| Escape / cancellation | Restore the original remote buffer, cursor, and relevant selection state; execute nothing. |
| Partially typed or edited command | Preserve the authoritative Readline content and cursor; do not reconstruct it from terminal echo. |
| Repeated keys while the widget is opening | Route them deterministically to their intended shell/widget interaction; never leak navigation or selection into a running command. |
| Vim, less, top, a REPL, `read`, a password prompt, or another foreground program | Preserve that program's keys and output. Do not hijack Ctrl-R or arrows. |
| Returning from a foreground program | Restore enhancement at the verified instrumented Bash prompt. |
| Exiting the destination SSH session | Restore the hub's own Atuin hostname, user, cwd, session, and keybindings without leaking destination context. |
| Special operations | Separate CLI commands may handle import, diagnostics, enable/disable, and recovery. They must not be necessary for ordinary history search. |

Reuse the native Atuin Bash widget's semantics where possible. Support normal Emacs bindings first and test Bash vi insert/command modes. Preserve Ctrl-P/Ctrl-N and custom bindings according to the tested Atuin/Readline configuration; do not blanket-intercept every arrow or control key. Respect explicitly disabled bindings. Normal Tab completion, cursor movement, deletion, undo, bracketed paste, and external-editor bindings must continue to work.

The remote Bash editor remains authoritative. Do not replace it with a local line editor that submits complete commands over SSH; that would change completion, editing, and interactive behavior.

## 3. Explicit boundaries and truthful guarantees

Interpret “no remote installation” as allowing session-only Bash functions, hooks, variables, and Readline bindings delivered through the encrypted SSH session. Prefer an entirely in-memory/file-descriptor bootstrap. Do not modify remote profiles, `.bashrc`, `.inputrc`, SSH configuration, executable directories, or services. Do not download dependencies on the remote host. Normal changes caused by Bash itself, such as its existing history persistence, remain normal shell behavior.

Reliable integration requires this temporary remote cooperation: Bash owns the actual command buffer, cwd, and command lifecycle. Do not claim that observing terminal keystrokes alone provides equivalent information.

“Without delay” means fast hub-local search and minimal middleware overhead. There are two connections: workstation-to-hub, and hub-to-destination. An authoritative destination Readline callback incurs transit over the second connection; returning a selection also uses it. Once open, search needs no destination or separate history-service round trip, but each terminal interaction still traverses the first connection. Measure both separately; a distant hub cannot feel local regardless of query speed. Do not promise literal zero RTT. Any speculative opening must preserve correctness under custom bindings and foreground programs before it is enabled.

Maintain connections with the behavior of normal OpenSSH. Preserve configured keepalives, disconnection behavior, and exit codes. Do not implement automatic command replay. A lost connection does not prove whether a remote command completed, and a new connection does not restore an old shell without remote persistent session management.

The initial enhanced scope is the hub's Bash plus each destination Bash directly instrumented by the bridge. Further hops launched from inside that destination, such as `sudo -i`, `su`, another `ssh`, container shells, and attachment to existing tmux/screen sessions must remain fully usable as terminal applications. Their inner shells are separate instrumentation scopes. Until explicitly supported and tested, pass them through and record only the outer command. Never invent inner host/user context from the visible prompt. Document this boundary and provide an extension plan; do not advertise enhancement in those shells merely because their output is visible.

Unsupported shells, restricted accounts, forced commands, incompatible hooks, and unsupported invocation forms must fall back cleanly to plain SSH where that is safe. Such fallback is a compatibility behavior, not evidence that the enhanced MVP has passed its acceptance gates.

## 4. Prove the Atuin and Bash integration surfaces

Before choosing the final implementation, inspect the installed Atuin version, its generated Bash integration, command help, and the corresponding official source. Record exact versions and supported capabilities. Use isolated Atuin configuration/data directories, Compose project/volume names, test keys, and local test state for experiments; never experiment on the user's production history.

Create `docs/COMPATIBILITY.md` with reproducible probes for:

1. Native TUI launch, result capture, cancel, insertion, acceptance, and keymap behavior.
2. Remote hostname, remote username, cwd, session, shell, and initial-query context.
3. Exact remote-account scoping, host/session/directory/global switching, and remote workspace behavior.
4. Native record creation/completion, privacy filters, timing, concurrent writers, and native record-store integrity.
5. Faithful historical import, unknown metadata, repeated imports, and database uniqueness behavior.
6. A temporary remote Bash bootstrap that preserves ordinary shell startup and editing behavior.

Inspect Atuin's existing experimental `pty-proxy` as a possible reusable component and as a coexistence case. If the user's local shell already runs it, prevent recursive proxying, duplicate capture, competing terminal ownership, or control-frame collisions. Do not automatically enable output retention or AI features as part of this history/search project.

Useful starting points verified in Atuin v18.24.1 include `ATUIN_HOST_NAME`, `ATUIN_HOST_USER`, `ATUIN_SESSION`, `ATUIN_SHELL`, `PWD`, `ATUIN_QUERY`, `atuin history start`, `atuin history end`, and `atuin search -i`. Reverify their actual semantics. Set context only for the relevant local Atuin invocation; do not change the parent shell's identity, HOME, configuration roots, credentials, or database location.

Do not assume these interfaces solve every requirement. In the reviewed version:

- Native host filtering deliberately spans users on a hostname; it does not guarantee exact remote-account filtering.
- Directory filtering is based on the path, which can occur on several hosts.
- Workspace discovery examines the local filesystem; setting remote `PWD` is insufficient.
- Some search flags apply only to noninteractive search, not to the native TUI.
- The Bash importer has multiline and synthesized-timestamp limitations.
- Native history uniqueness can collide across hosts; prove preservation rather than relying on an ignored insert.

Prefer the unmodified installed Atuin binary. If required behavior cannot be expressed through its existing interfaces, build the smallest isolated, version-pinned upstream-native compatibility extension. Keep orchestration, SSH, protocol, import coordination, and packaging in Python 3.14. Build any native compatibility component inside a separate Docker build stage; do not require a Rust toolchain on the Windows host. Clearly disclose any necessary native component and preserve Atuin's real TUI and storage/record machinery. A native extension must have reproducible builds and a distinct executable; do not silently replace system Atuin, introduce a custom lookalike UI, or mutate a production database schema.

Before opening production history for writes, any native helper must verify compatibility with the installed Atuin and its storage version. An Atuin upgrade must safely disable an incompatible helper, leaving ordinary SSH/Atuin usable; it must never trigger a downgrade, unexpected migration, or speculative writes to a newer database.

If a gap requires a schema or upstream change, reproduce it against disposable data, preserve affected records as explicitly pending, and report the exact remaining gap. Do not falsify metadata or declare an incomplete capability complete. Continue all unaffected implementation work.

## 5. Architecture requirements

### 5.1 Front terminal, native UI, and backend SSH PTY

Implement the user's proposed front/back separation inside the hub. The hub's Bash is the ordinary entry shell and initializes Atuin. When an eligible `ssh` starts, a Python PTY controller becomes the foreground terminal owner for that session. It manages a separate backend PTY containing the real OpenSSH client. In normal mode, the controller forwards input/output transparently between the inbound SSH terminal and that backend. On a valid destination Readline history request, it temporarily gives the front terminal to the actual hub-local Atuin TUI, then restores the backend view and returns the result through the waiting destination binding.

Treat terminal rendering, command editing, and command execution as distinct responsibilities. The controller schedules terminal ownership; native Atuin owns the search UI; destination Bash owns its Readline buffer and executes its commands. There must be exactly one eligible input consumer at a time. A second interactive Bash does not automatically intercept keys while its foreground SSH child owns the terminal. Do not solve that by having a front Bash parse, expand, execute, and resend the destination's commands, or by reconstructing remote state from screen text.

Keep the implementation lightweight: the controller, native TUI, and OpenSSH may be processes within one hub container. They do not need separate Docker services or a custom web UI. A persistent session multiplexer may be an optional later convenience for reattaching to the hub; it is not required for native search, and it cannot by itself preserve a destination shell after its SSH transport is lost.

### 5.2 System OpenSSH owns SSH

Wrap the actual OpenSSH client executable inside the hub with argument arrays. The inbound workstation SSH client and hub sshd remain ordinary OpenSSH components. Preserve SSH configuration, authentication, host-key validation, certificates, agent use, jump hosts, proxies, forwarding, compression, and multiplexing. Do not reimplement SSH with Paramiko or another transport for the MVP.

Automatically enhance ordinary interactive shell invocations. Conservatively pass through explicit remote commands, pipelines, subsystem requests, forwarding-only/background invocations, configuration/query modes, and incompatible `RemoteCommand` cases. Handle `-N`, `-T`, `-W`, `-s`, `-O`, `-G`, `-Q`, `-V`, `-n`, `-f`, combined options, `--`, and destination parsing correctly. Existing `-t` interactive command invocations must retain normal SSH behavior even where enhancement is unsupported.

Use OpenSSH's own configuration evaluation where appropriate. Do not change authentication policy, disable host-key checking, require new sshd settings, override a user's chosen remote command, or kill a shared ControlMaster. Own and clean up only processes/sockets created by this application.

### 5.3 A byte-oriented PTY relay

Use an explicit event loop with bounded buffers, partial-write handling, EOF/error handling, and lifecycle management. Python's PTY/termios/selector primitives are suitable building blocks; a trivial `pty.spawn()` wrapper is not a complete design.

Preserve all normal output, including stdout/stderr as presented by the remote PTY, colors, Unicode, control sequences, progress displays, alternate screens, mouse events, terminal queries, and bracketed paste. Do not line-buffer, normalize, or decode/re-encode ordinary transport bytes. Remove only validated frames belonging to the negotiated control protocol. Do not strip unrelated OSC/DCS sequences.

Propagate initial terminal dimensions and subsequent resizes. Preserve Ctrl-C, Ctrl-D, Ctrl-Z, job control, `fg`, SSH escapes including `~.` and suspension, and process exit status. Handle signal delivery without sending interrupts twice.

When the native local Atuin TUI owns the terminal, route input exclusively to it. Retain remote output arriving in the meantime, preserve ordering, and replay/drain it appropriately on return. Specify a bounded overflow policy: backpressure, secure transient spooling, or canceling the widget and resuming output. Never silently drop output or allocate unlimited RAM. Test the selected policy against sustained background output.

Restore terminal state and process groups on normal exit and handleable failures. Atuin/UI/database worker failures must not tear down an otherwise healthy SSH session. Do not promise recovery from SIGKILL, power loss, or failure of the entire relay process; document terminal recovery commands for those cases.

### 5.4 Session-only remote Bash integration

Use structured shell events and Readline callbacks. Bootstrap after authentication without contaminating the command line or history and without relying on brittle prompt regexes.

Prove login/startup equivalence. Passing a bootstrap command to SSH changes startup semantics; `bash --rcfile ... -i` alone does not reproduce a login shell. Preserve the relevant system/user startup order, aliases, functions, environment, shell options, existing history policy, prompt, and logout behavior. Avoid sourcing profiles twice. Test custom prompts and startup output.

Compose with existing DEBUG/EXIT traps, string/array `PROMPT_COMMAND`, preexec frameworks, and existing Atuin integrations. Detect incompatible or replaced hooks and report degradation without damaging the session. Do not overwrite unrelated user hooks or change `set -e`, `pipefail`, job control, or other shell semantics to simplify capture.

The remote history binding must obtain authoritative `READLINE_LINE`, `READLINE_POINT`, and relevant mark/keymap state. A waiting callback receives an explicit insert/accept/cancel result and changes Readline through its supported mechanisms. Preserve native acceptance behavior. Transport selected commands as encoded data; never use `eval`, synthesized backspaces, or a raw command plus newline as the insertion mechanism.

Handle long/multiline commands, quotes, control characters allowed by the shell representation, Unicode cursor units, and trailing newlines. Account for Bash string/NUL limits and PTY canonical-mode input limits. Do not assume shell command substitution preserves trailing newlines.

### 5.5 A small control protocol and state machine

Specify protocol version, capabilities, session/shell IDs, monotonically increasing event sequence, command IDs, request IDs, generation, encoding, maximum lengths, chunking, cancellation, timeout, and resynchronization.

Model at least authentication/bootstrap, passthrough, instrumented shell, command running, widget request/wait, local widget active, restore, degraded, and closing states. Shell callbacks determine eligibility for history search; a cached prompt flag alone cannot prove the current input consumer.

Specify an input-ownership handshake or an equivalent proven protocol for type-ahead during activation. Ctrl-R immediately followed by query letters, arrows, or Enter can put bytes on the SSH connection before the local relay receives the remote callback. Correctly recover/route those bytes; a local `TUI active` flag alone is insufficient. Handle cancellation and resumption with the same care. At 150 and 300 ms RTT, Ctrl-R followed immediately by typing must produce exactly the intended local search query, with no lost characters, protocol contamination, or stray remote command.

Treat all remote strings as untrusted data. Per-session nonces prevent accidental frame confusion but do not authenticate a hostile remote process. Frames must not trigger arbitrary local commands, file access, credential exposure, or configuration changes. Only a response matching the current waiting request may update Readline. A stale result must never become input to a different shell or program.

Evaluate in-band and separate-channel transport explicitly. The default must not require a remote daemon, remote Python, exposed listener, forwarding permission, or changed sshd configuration. Prove framing under split reads, coalesced writes, malformed input, unrelated escape sequences, and realistic concurrent output. On loss of synchronization, preserve safe SSH interaction and avoid guessing command boundaries.

## 6. Native Atuin functionality, context, and storage modes

### 6.1 Native client state and context

Use the hub user's real native Atuin history and configuration. Records must be visible through ordinary Atuin in the hub after an onward SSH session ends. Preserve native record-store integrity while all network synchronization stays disabled. Do not create a custom canonical history database or a synchronization protocol. A bridge outbox, import ledger, and provenance store are allowed as implementation metadata. Provide an explicit local migration/import route for existing history, without importing Atuin login credentials or enabling sync; do not claim to reuse a workstation database that was never connected.

Preserve native search modes, ranking, themes, keymaps, Up-specific settings, details/inspector, deletion, context switching, and insert/accept/cancel actions where available in the supported Atuin release. Build a capability matrix and test these features, including configured daemon-backed search. Never silently substitute a custom Python TUI.

The default enhanced search scope is the current remote machine and effective remote account, across that account's recorded sessions. Allow normal navigation to current session, machine-wide, directory, workspace when available, and global history. Distinguish exact account scope from native host scope in implementation and documentation. Switching to global must actually remove the initial account restriction.

Remote directory scope means the current remote host, account, and path together; remote workspace scope applies that same identity plus the actual remote workspace. Test identical paths on different machines/accounts. Broader native path-only or machine-wide searches may be exposed deliberately, with their scope clear.

Record canonical destination host/user context, not the workstation or hub host/user. Preserve SSH destination, alias, effective connection parameters, and identity mapping separately where needed. Define deterministic mapping for multiple SSH aliases to one server and for different machines with identical hostnames; do not silently merge unrelated hosts or manufacture hostnames to fake account filtering. Do not confuse Atuin's local native record-writer identity with the machine on which the command executed.

Capture cwd before command execution; after `cd`, subsequent searches use the new remote cwd. Paths need not exist locally. Never change the local process working directory to a remote path or infer a remote Git workspace from a same-named local repository. Obtain remote workspace metadata only when available and integrate it through a verified native context mechanism.

Give every instrumented remote shell a distinct stable session ID, separate from the enclosing local shell's Atuin session and concurrent SSH sessions. Preserve real repeated executions. Search scope, record identity, and retry deduplication are separate concerns.

### 6.2 Local hub and central LAN hub

Use the same native local storage implementation in both deployment layouts:

| Layout | Operation | History location |
| --- | --- | --- |
| Local hub | Run the container on Windows/Linux and enter its shell through the published local port. | Native Atuin state in that Docker host's local persistent volume. |
| Central LAN hub | Run the container on a LAN server or NAS and enter it from any authorized device over SSH. | One native Atuin installation and local persistent volume on the central host; concurrent sessions use that same installation. |

The central hub itself is the shared LAN history environment. Atuin UI, capture, search, and database operations run there; the workstation carries only the SSH terminal interaction. There is no separate Atuin sync server, hosted API, or account registration. Ordinary SSH public-key authentication protects entry to the hub.

Keep native SQLite and related files local to the machine running Atuin. Do not place the live database on SMB/NFS, expose SQLite through a network share, or concurrently attach a copied native state directory to independent hubs. Different clients entering one hub use its normal local concurrent-writer behavior.

Document that choosing a central hub is different from operating several independent local hubs. Independent hubs do not automatically share history. A stopped-volume migration/restore preserves one installation; an explicit native-compatible import may merge historical data with clear provenance and collision handling. Do not invent a hidden account or synchronization service to bridge this distinction.

The local hub works without internet. The central LAN hub works without internet while the LAN and host are reachable; if that host or connection is unavailable, its shell and history UI are unavailable. Do not claim an offline client cache or silently switch to another database. A user may deliberately run a separate local hub, whose history remains separate.

Provide easy SSH aliases/examples for selecting the intended hub from any workstation. A stable LAN hostname or address belongs to the hub; do not make it an Atuin `sync_address`.

### 6.3 No-account configuration and privacy

Set and verify the effective native configuration:

```toml
auto_sync = false
update_check = false
```

Do not provision Atuin login/session credentials, call `atuin register`/`atuin login`/`atuin sync`, or use the native Atuin sync server. Its normal protocol is account-based, including when self-hosted; it does not meet the user's no-account requirement. Do not implement anonymous access to that protocol, strip its authentication, or silently create an account on the user's behalf.

A native local daemon is allowed for search/capture performance only. Give it one lifecycle owner and a local Unix socket. Prove that daemon, shell hooks, compatibility helpers, and UI perform no automatic outbound history/sync/update/telemetry requests. Do not assume a single setting controls every code path. Avoid importing old login state or environment overrides from a previous synchronized installation.

Do not enable cloud/AI providers, remote model fallbacks, telemetry, webhooks, or output uploads. Native history/search features remain in scope. Privacy filters must run before history enters the DB, outbox, diagnostics, or backup staging. Do not store raw terminal/password input or command-output transcripts by default.

Protect the hub with SSH keys, normal host-key verification, non-root user sessions, owner-restricted state files, and local/LAN-only ingress. Bind examples to localhost or a chosen LAN interface; do not rely on a broad `0.0.0.0` bind alone as proof of LAN restriction. Provide explicit firewall guidance; create no internet port forwarding, public tunnels, or remote-access service enrollment.

Native local SQLite history is not guaranteed encrypted at rest by these settings. Document filesystem permissions and optional host disk/volume encryption and encrypted backup handling accurately. Preserve any locally generated native storage keys required by Atuin; those do not imply an Atuin account or authorize network use.

Validate the privacy boundary with request/network observation while exercising startup, search, recording, idle daemon operation, restart, import, and upgrade checks. Tests must detect attempted outbound requests as well as successful connections. Keep package/image downloads at explicit build/update time separate from runtime history activity. Do not disable the hub's requested outbound SSH or other intentional network commands as a substitute for fixing an unwanted background request.

A separate account-free LAN history backend for multiple independently running hubs would be a new, explicitly designed feature with its own native-adapter and consistency work. It is not supplied by stock Atuin and is not part of this MVP's central-hub layout. Do not add it without a later explicit scope change.

## 7. Command capture, persistence, and failure recovery

Define one history entry as one user-submitted interactive Bash command or compound command, including multiline input. Internal commands in functions, loops, pipelines, substitutions, and the bridge's own hooks must not create duplicate user-history entries.

Capture the accepted command representation, remote host/account, shell, cwd at start, session ID, start time, and observed completion status/duration. State whether history expansion follows native Atuin behavior. Observe the final shell status before helper commands can overwrite it. Preserve `$?` and relevant pipeline status semantics for the user.

Document time sources and precision. Do not substitute delayed local ingestion time for the actual known remote start time. Account for clock skew and clock adjustments; use monotonic elapsed time where the chosen remote mechanism provides it, and disclose estimation or limited resolution where it does not. A metadata-capable native adapter may be necessary for delayed/replayed events.

Treat blank input, input canceled before execution, rejected syntax, interrupted running commands, background launches, `exit`, `exec`, and lost connections explicitly. A background launch's shell status is not the eventual background process's result. Missing completion remains incomplete/unknown using supported Atuin conventions; never invent success, exit status, or precise duration.

Use native Atuin CLI, a verified native daemon interface, or the isolated compatibility extension for writes. Do not write raw SQL into Atuin tables or assume its SQLite file alone represents its complete native record state. Respect recording filters and deletion/tombstone semantics.

Decouple capture persistence from the terminal relay and hub-local search. Use a durable local outbox with strict permissions, per-session sequence tracking, bounded retries, corruption detection, and reconciliation. Apply privacy/exclusion rules before durable payload storage. Do not retain raw passwords, arbitrary terminal input, output transcripts, or excluded commands in logs/outboxes by default.

Define the durability boundary honestly: once an event has been durably accepted locally, recover it without silent loss. Events never delivered by the remote side cannot be guaranteed after a network failure. Distinguish these cases in diagnostics.

In healthy operation, a command must be searchable immediately when the user returns to the prompt and presses Up/Ctrl-R. Coordinate the asynchronous writer and native search with an ordered local visibility barrier or equivalent mechanism. It must not wait for any network history service or a remote history scan. Test immediate recall, delayed writers, and concurrent sessions. On storage failure, keep search usable and clearly report pending history rather than silently presenting stale results as current; never impose an unbounded wait.

Prove replay/idempotency against the actual write interface. A CLI commit followed by a crash before saving its returned ID is an ambiguous commit window; command-text deduplication is not an acceptable solution. Use stable event identity and a verified reconciliation mechanism. If exact replay cannot be proven, preserve and surface ambiguous events instead of inserting guessed duplicates.

Avoid synchronous Atuin startup or disk work on every transported keystroke. Remote execution must not depend on a successful local database write. On DB busy/read-only/full, worker failure, or Atuin failure, preserve SSH, report a concise degradation, and retain recoverable events where storage is available. Document the unavoidable loss boundary when local durable storage itself is unavailable.

## 8. Remote history import

Provide an explicit import command for an identified SSH target/account, with dry run, maximum entries/bytes, optional time bounds, resumability, and an idempotent repeat operation. Import should not block initial login or interactive search. Automatic import on every connection is not the default.

Read the permitted remote Bash history file over the authenticated connection or a clearly owned compatible auxiliary SSH session. Discover the actual configured `HISTFILE`; do not assume every account uses `~/.bash_history`. Never execute history content, require sudo, alter remote history settings, truncate history, or read a different account's files. Do not force the active shell to flush/rewrite its history without an explicit import option. Explain that commands held only in other shells' memory may be absent.

Retain supported Bash timestamps, multiline command boundaries, Unicode, and repeated command occurrences. Timestamp-less multiline files can be ambiguous: document and report ambiguity rather than invent perfect reconstruction. Do not fabricate old cwd, session, exit code, or duration. Where Atuin requires a non-null value, use a documented native unknown/import convention and retain original provenance; identify synthetic timestamps as synthetic.

Maintain a per-source import ledger that handles unchanged re-import, append, rotation, truncation, overlapping snapshots, and partial failure. Deduplicate occurrences, not command text. Include host/account/source identity and original timestamp precision where known.

Test two hosts/accounts with the same command and timestamp and unknown cwd. Detect native storage collisions and report retained/pending conflicts; never count an ignored insert as success, silently alter factual metadata, or change the user's schema. Apply the same privacy policy before import persistence; do not assume every native importer applies capture-time filters.

Dry run must show counts, parse quality, filters, duplicates, ambiguous entries, and prospective collisions. A completed import reports source, imported/skipped/pending counts, and limitations. Records successfully imported must be usable through ordinary local Atuin and its native local record machinery.

## 9. Responsiveness and performance targets

These are engineering targets to measure, not claims already demonstrated:

- With 100,000 history records, target p95 local widget launch overhead at most 100 ms after receiving the authoritative remote request, and p95 query/navigation response at most 50 ms once open.
- Target p95 added local relay latency at most 5 ms under normal interactive load. Report measurement method and comparison with direct OpenSSH.
- Measure cold/warm startup, first-results latency, key-to-visible-widget latency, and result-to-remote-buffer latency separately. Publish reference hardware, software versions, history size, sample count, and p50/p95/p99.
- Measure workstation-to-hub and hub-to-destination latency independently. Test local/LAN ingress and destination RTT around 50, 150, and 300 ms. Search/navigation after opening must not add a destination or separate history-service round trip per key; terminal input/rendering still uses the workstation-to-hub link.
- Test 10,000, 100,000, and 1,000,000 local history records and multiple simultaneous SSH sessions. Report scaling limits and native Atuin costs separately from bridge overhead.
- No model, cloud service, history synchronization endpoint, remote history scan, or network-dependent freshness check may be required on the search hot path.

Use existing native Atuin caching/daemon capabilities where appropriate and verified. Do not create a second custom history search index merely to pass a superficial benchmark. Never improve latency by weakening context correctness, password/input handling, or terminal integrity.

## 10. Docker packaging, persistence, and operation

### 10.1 A small, ordinary Linux shell environment

Build a reproducible multi-stage image using a pinned supported Python 3.14 Debian-based slim image. Include GNU Bash, OpenSSH client/server, native Atuin, the installed Python bridge, CA certificates, suitable locale/terminfo support, and a small set of useful tools such as curl, Git, less, and an editor. Use a dev stage for compilers/test dependencies. Record image size; choose compatible components rather than minimizing bytes at the expense of Bash or terminal behavior.

Create one personal non-root shell account for the MVP, with configurable username and stable hub hostname. Hub shells, Atuin, and middleware run as that account. sshd may use the privileges needed for ordinary session creation; prohibit root SSH login and do not require Docker privileged mode or the Docker socket. Initialize native Atuin and the bridge exactly once for interactive Bash while preserving user customization and noninteractive commands.

Use an idempotent entrypoint, predictable daemon lifecycle, foreground sshd, appropriate signal forwarding/child reaping, health/readiness checks, and graceful shutdown. Avoid a full systemd installation. No remote history service may be a health/readiness dependency. After initial setup, support `restart: unless-stopped`; document Docker/host startup requirements. Docker Desktop and its host must be running for the hub to be reachable.

Keep OpenSSH behavior available: interactive authentication to destinations, port forwarding, SCP/SFTP, host-key checking, configured proxies, and normal terminal tools. An ordinary `curl`, `git`, or `ssh` from the hub should use its normal network stack.

### 10.2 Compose and developer workflow

Deliver these purposeful files, or a comparably simple documented layout:

| Deliverable | Purpose |
| --- | --- |
| `Dockerfile` | Reproducible runtime/dev/test stages; production image contains installed application code. |
| `compose.yaml` | Single-user shell hub and local persistent volumes; usable locally or on a LAN host without an Atuin account. |
| `compose.dev.yaml` | Optional source bind mount for Windows/Linux editing; independent development state. |
| `compose.test.yaml` | Disposable destination sshd fixtures, test hub, client sessions, and runtime network-observation tests. |
| `.env.example` and example config | Nonsecret hub host/port settings, key paths, and explicit local-only Atuin settings. |
| `scripts/*.ps1` and Linux equivalents | Setup, build, start, doctor, verification, backup, restore, and migration entry points. |
| `.gitattributes` and `.dockerignore` | LF for Linux scripts; exclude credentials, history, private state, and unnecessary build files. |

Use a normal Python package with `pyproject.toml`, a lockfile, a console entry point, and minimal runtime dependencies. Install it into the image and test the installed build. All Python/native compilation happens in Docker. A production container must run without a source bind mount or the original checkout.

A Windows user should be able to configure a public key, set a few nonsecret settings, and then use PowerShell:

```powershell
docker compose build
docker compose up -d
ssh -p 2222 hubuser@localhost
```

These are the intended commands after setup; implement the documented service names, user, and port or update every example consistently. Deliver a short native Windows quickstart and a Linux quickstart. Host automation must handle paths with spaces and Windows quoting. Do not require Bash/Make/WSL on Windows to run the ordinary developer lifecycle.

Use separate Compose project names and volumes for production, development, and tests. Test cleanup must never target production resources. Routine stop/rebuild/update commands must preserve named volumes; do not include `down -v` in them. Use LF files and set executable bits inside image builds instead of depending on NTFS Unix permissions.

### 10.3 Local and LAN access

Use a standard Compose bridge network and publish the hub SSH port on the Docker host, initially host port 2222 to container port 22. Make bind address and port configurable. Default to `127.0.0.1` for host-only access. The LAN example must bind a selected LAN interface/address and describe the corresponding LAN-only firewall rule; a broad bind requires an explicit reason and equivalent filtering. Other LAN devices connect to the Docker host's LAN IP/DNS and published port. Test authorized access from a second machine and reject access outside the configured boundary.

The portable baseline does not give the container an independent DHCP/LAN IP or make broadcast discovery identical to a physical computer. Do not require macvlan, host networking, a static container IP, router changes, or privileged network access. Destination servers see the routed/NATed network source chosen by Docker/host networking. An optional future Linux-only independent LAN identity must not become an MVP dependency.

Verify outbound LAN access by IP, LAN DNS, internet DNS/HTTPS, and onward SSH. DNS, VPN routes, and firewall policies need their own diagnostics. Do not assume host-only `hosts` entries or mDNS work inside the container. Support documented DNS overrides without hardcoding the user's subnet. Explain `host.docker.internal` for reaching services on Docker Desktop's host and provide a tested Linux equivalent only when needed.

### 10.4 Persistent state and credentials

Persist local state on Linux-backed Docker named volumes by default. On Windows these are still local to the PC, managed inside Docker's storage. Keep the active SQLite databases off Windows source bind mounts and network shares. Expose database-aware backup/export into a normal host folder for convenient file access. A native Linux bind-mount alternative may be documented and tested.

Use an explicit native client root, such as `ATUIN_HOME=/state/atuin` for the pinned compatible release, and persist its full state. Configuration may be supplied from a host-editable config directory, with a documented one-way override/initialization policy; never overwrite customized config on restart. Verify effective native paths and avoid ambiguous old/new default layouts. Give isolated profiles distinct daemon sockets in a runtime directory; sockets themselves are not portable backups.

Preserve:

- Native history DB, record store, metadata/writer identity, any native local storage keys, and configuration; no Atuin login/session credentials.
- Bridge outbox, import/provenance ledger, and any necessary reconciliation state.
- The user's persistent home/work files, Bash customizations, SSH config, and destination `known_hosts`.
- sshd host keys in a distinct persistent server-key location, so recreation does not change fingerprints.

A new empty deployment generates fresh host keys and a fresh native client identity. The reusable image must contain no generated identity, personal history, authorized keys, secrets, or private keys. Supply inbound `authorized_keys` at runtime and initialize correct Linux ownership/modes. Keep this distinct from the credentials used for outbound SSH. Provide a documented dedicated outbound key/config setup with protected persistent storage; agent forwarding is optional and explicit, not a requirement or broad default.

### 10.5 Integration, diagnostics, backups, and upgrades

Inside the hub, provide interfaces such as:

```bash
atuin-ssh doctor
atuin-ssh connect -- myserver
eval "$(atuin-ssh init bash)"
ssh myserver
atuin-ssh history import --target myserver --dry-run
atuin-ssh history import --target myserver
```

These names describe the tool to implement. Initialization is automatic in ordinary hub logins; the explicit command is useful for diagnosis. Use a reversible Bash function or equivalent to route eligible interactive `ssh` calls. Keep the actual executable as a bypass; do not replace `/usr/bin/ssh`, break scripts, recursively invoke the wrapper, or silently overwrite existing functions. Provide enable/disable controls that manage only this tool's integration.

`doctor` must report versions, image/platform, terminal characteristics, effective state locations, active integration, capability results, local/LAN hub location, effective disabled sync/update settings, daemon readiness, and pending/failed events. Include a sanitized diagnostic bundle. Exclude command bodies, keys, credentials, full environments, and transcripts by default.

Provide backup/restore commands runnable from PowerShell or Linux. Back up all relevant local Atuin state, hub SSH identity, and bridge metadata using a consistent procedure. For the simple reliable route, stop/quiesce all writers and copy the complete relevant state; any online backup must use verified SQLite/native mechanisms and account for all databases and WAL files. Copying an active `history.db` alone is insufficient. Test restoration into fresh volumes.

Distinguish restoring/moving the same stopped hub from creating another independent hub with fresh local state. Document upgrade compatibility and backups before migrations; do not promise an image downgrade can safely read a migrated database. The central hub still needs backups of its history, configuration, SSH identity, and recoverable events.

## 11. Required verification

Use disposable containerized OpenSSH destination servers and isolated Atuin state for automated integration tests. Exercise the real two-hop workstation-client → hub sshd → bridge → destination sshd path, including the outer terminal's raw-mode and resize behavior. Test actual PTY sessions and actual installed Atuin. Mocks can test components but cannot establish end-to-end behavior. Keep fixtures, expected outcomes, and reproducible commands in the repository.

| Acceptance area | Minimum evidence |
| --- | --- |
| Native keys — defining gate | Up/Ctrl-R at both hub and destination prompts; native navigation, configured Up behavior, insert, accept/cancel, partial buffer/cursor, immediate type-ahead, vi/Emacs modes across both SSH hops. |
| Shell editing | Completion, undo, external-editor binding, multiline prompts/input, Unicode, quotes, long commands, bracketed paste, interrupted editing, terminal resize during search. |
| Interactive applications | Vim/nano, less, top/htop, REPL, `read`, password prompt, interactive confirmation, `cat`, Ctrl-C/Ctrl-Z/fg/Ctrl-D. |
| Command lifecycle | Pipelines, functions, aliases, loops, subshells, substitutions, `&&`/`||`, heredocs, history expansion, nonzero status, background launch, exit/exec, disconnect. |
| Startup/hooks | Ordinary login setup, startup output, profiles exactly once, existing traps/preexec, string/array PROMPT_COMMAND, custom shell options, existing Atuin. |
| Attribution | Two hosts, two accounts on one host, same hostnames on different targets, aliases, concurrent sessions, cwd changes, remote-only paths and Git roots. |
| Nested scopes and return | Further sudo/su/SSH/container/tmux scopes remain usable without false records; leaving the destination restores the hub's own context and keys. |
| Native SSH | SSH config aliases, key/password/keyboard-interactive authentication, agent, jump host, port override, forwarding, multiplexing, configured remote command, bypass modes, SSH escapes. |
| Output/protocol | Byte-preserving baseline comparisons, sustained/background output during TUI, terminal escapes, fragmented/malformed/truncated/oversized frames, stale results, loss of synchronization. |
| Storage/recovery | Actual Atuin visibility and native record integrity, concurrent writers, delayed completion, retries, crash at commit boundaries, DB busy/read-only/full, worker/TUI failures, and disconnection of either SSH hop. |
| Import | Timestamped/untimestamped and multiline histories, repeats, append/rotation/truncation, unknown fields, filters, host collisions, dry-run accuracy, resumability. |
| No installation | Remote filesystem/profile comparison allowing only expected pre-existing shell behavior; no installed project files/services or residual bootstrap history. |
| Native Windows | Actual Windows Terminal/OpenSSH → published hub port → destination smoke test; native PowerShell build/setup/test/backup lifecycle. No separately managed WSL development distro. Mark unverified until run on Windows. |
| Linux portability | Same image/Compose on native Linux Docker Engine; actual network, persistence, terminal, and restore smoke tests. State tested CPU architecture. |
| Image and persistence | Fresh image contains no private state; installed package works without checkout; recreate hub and retain history, identities, home/config, and pending events. |
| Local/LAN layouts | Local hub without internet; two authorized workstation sessions sharing the same LAN hub; immediate history visibility with correct context; central host restart; independent hubs remain separate. |
| No accounts or external history traffic | Fresh install, startup, recording/search, daemon idle/restart, import and diagnostics require no Atuin registration/login and produce no automatic outbound history, sync, update, telemetry, or AI requests. |
| LAN reachability | Host and second LAN machine can enter published SSH port; hub resolves/reaches LAN and internet targets; local DNS and configured VPN cases are reported separately. |
| Backup/migration | Consistent complete-state backup, restore to clean volumes, move a stopped hub, and create a separate independent hub without copied credentials or concurrent cloned writer state. |
| Performance | Reproducible local-overhead and RTT-separated latency benchmarks at the specified history sizes. |

Use differential tests against plain OpenSSH for terminal/startup behavior and native local Atuin Bash integration for widget semantics. Include meaningful fault injection. A test must verify a behavioral contract, not simply mirror an implementation function.

## 12. Delivery sequence and completion criteria

1. Inspect repository/instructions, document the three-machine model, and probe the pinned local Atuin/Bash interfaces. Record compatibility gaps with reproductions.
2. Build the minimal hub image/Compose: native SSH login, ordinary Bash, native Atuin, persistent local state, working outbound network, and a native Windows developer entry point. Prove recreation retains state. This foundation is not completion of onward SSH enhancement.
3. Prove the defining vertical slice across both SSH hops: temporary destination binding, native hub Atuin, authoritative buffer/cursor round trip, insert/accept/cancel, correct key ownership, immediate type-ahead, and measured latency.
4. Harden byte relay, startup compatibility, terminal ownership, cancellation, resizes, and foreground-application passthrough.
5. Add accurate command capture, remote context, native storage/record integration, filtering, immediate recall, durable recovery, and concurrency.
6. Verify the central LAN hub layout with multiple authorized workstation sessions sharing its local history. Enforce no-account/no-external-history behavior and document independent-hub and availability boundaries.
7. Implement faithful bounded import with provenance/idempotency/collision handling, including repeated or overlapping imports from workstation sources without claiming automatic multi-hub merging.
8. Finish packaging, PowerShell/Linux operations, backups/restores, acceptance tests, benchmarks, and actual Windows/Linux validation or a precise list of remaining manual gates.

Maintain a concise checklist with completed, failing, blocked, and unverified items. Make small reviewable commits where repository workflow permits. Keep decisions and limitations in durable project documentation so another Codex session can continue.

Deliver source, reproducible images/build instructions, Compose files, tests, setup/operation scripts, example configuration, Windows/Linux quickstarts, architecture/protocol notes, compatibility matrix, diagnostics, backup/restore instructions, benchmark results, and a continuation handoff. Use focused modules for SSH invocation, PTY relay, terminal ownership, protocol, Bash integration, Atuin integration, history/outbox, import, and diagnostics; avoid unnecessary custom services.

The MVP is complete only when the default native-key interaction inside onward SSH, correct destination context, complete supported command capture, normal Atuin interoperability, local/LAN modes, import, persistent deployment, and SSH compatibility have evidence. List every remaining parity gap and whether it blocks the requested MVP. Do not replace end-to-end evidence with unit-test counts.

At the end, give exact setup/start/login commands, tested versions/architectures, passed/failing/manual gates, measured performance, material limitations, and the next concrete action. Begin implementation with the container foundation and native remote-key proof.

## Source anchors for implementation research

These are reference points, not substitutes for checking the installed version. Source observations were reviewed against Atuin v18.24.1 on 2026-10-23. Use versioned documentation/source where it disagrees with moving latest documentation. Verify image availability and runtime behavior; this brief is not a claim that the project or image has already been built.

- [Atuin basic usage](https://docs.atuin.sh/latest/guide/basic-usage/) and [configuration](https://docs.atuin.sh/latest/configuration/config/).
- [Atuin configuration, including disabling automatic sync and update checks](https://docs.atuin.sh/latest/configuration/config/). [Atuin sync setup](https://docs.atuin.sh/latest/guide/sync/) documents the account-based workflow excluded from this project.
- [Pinned client path resolution](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-common/src/dirs.rs) and [native identity metadata](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-client/src/meta.rs).
- [Docker commands from Windows without a separate distribution](https://docs.docker.com/desktop/features/wsl/), [Desktop networking](https://docs.docker.com/desktop/features/networking/), [port publishing](https://docs.docker.com/engine/network/port-publishing/), [volumes](https://docs.docker.com/engine/storage/volumes/), and [macvlan platform limits](https://docs.docker.com/engine/network/drivers/macvlan/).
- [SQLite WAL requirements](https://sqlite.org/wal.html) and [online backup API](https://sqlite.org/backup.html).
- [Atuin shell integration](https://docs.atuin.sh/latest/guide/shell-integration/) and [experimental pty-proxy](https://docs.atuin.sh/latest/reference/pty-proxy/).
- [Atuin Bash shell integration](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin/src/shell/atuin.bash).
- [Atuin command origin/context overrides](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-domain/src/record/cmd_origin.rs).
- [Atuin context and database filtering](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-client/src/database.rs).
- [Atuin cwd/workspace utility code](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-common/src/utils.rs).
- [Atuin history CLI](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin/src/command/client/history.rs) and [search CLI/TUI entry point](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin/src/command/client/search.rs).
- [Atuin Bash importer](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-client/src/import/bash.rs), [imported history builder](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-client/src/history/builder.rs), and [history uniqueness schema](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-client/migrations/20210422143411_create_history.sql).
- [Atuin native daemon history protocol](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-daemon/proto/history.proto) and [search protocol](https://github.com/atuinsh/atuin/blob/v18.24.1/crates/atuin-daemon/proto/search.proto).
- [GNU Bash builtins — bind](https://www.gnu.org/software/bash/manual/html_node/Bash-Builtins.html), [Bash variables](https://www.gnu.org/software/bash/manual/html_node/Bash-Variables.html), and [startup files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html).
- [OpenSSH ssh manual](https://man.openbsd.org/ssh) and [ssh_config manual](https://man.openbsd.org/ssh_config).
- [Python 3.14 PTY](https://docs.python.org/3.14/library/pty.html), [termios](https://docs.python.org/3.14/library/termios.html), and [selectors](https://docs.python.org/3.14/library/selectors.html).
- [uv tool installation](https://docs.astral.sh/uv/guides/tools/).
