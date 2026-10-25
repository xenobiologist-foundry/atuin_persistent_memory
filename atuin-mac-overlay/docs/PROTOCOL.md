# Mac transport and ownership

The encrypted SSH PTY carries ordinary terminal bytes and bounded nonce/sequence
OSC control frames. HANDOVER fences, READY after native negotiation and a complete
first frame, then RELEASE return ownership to the same editor. A relay has one input owner: OpenSSH,
waiting callback or native UI. Editor suggestions run in one bounded background
worker; new typing invalidates stale responses. Real OpenSSH keeps its argv and
owns authentication, configuration, host keys and connection management.

On Darwin, the relay uses `openpty` plus `posix_spawn` of the tiny C controlling
terminal helper. The child becomes a session leader, acquires its PTY and execs
the requested executable. No Python runs after fork in the multithreaded relay.
READY is a nonblocking inherited pipe descriptor. The native patch consumes that
descriptor using Rust's owned `File::from_raw_fd`. Initial queries over 64 KiB use
a bounded anonymous socketpair; the native process reads at most 256 KiB plus
one byte. No typed-query file or `/proc` path is used. Owned query/READY descriptors
are closed after use; ordinary descriptors are close-on-exec.

Local editing stays in zsh ZLE and uses the pinned native Atuin integration.
Startup wrappers source each ordinary file once with its normal ZDOTDIR, then
restore that directory before unrelated child shells can inherit it. Activation
runs before the first ZLE prompt. Existing Atuin hook names are removed before a
single initialization, and each shell receives a new native UUID. The local
widget uses the native compatibility UI's tagged result file to preserve exact
Unicode/trailing newlines and distinguish insert/accept. Cancel restores buffer,
cursor, mark and keymap. Native search configuration and Up behavior are retained.

Only coordination metadata is in bridge SQLite databases. All canonical history
and record writes go through native Atuin APIs; suggestion row lookups are bounded
read-only queries of checked native IDs. Version/migration checks precede local
activation and bridge writes. No record schema changes are made.

## Wire format and bounds

Frames are `ESC ] 777;atuin-ssh;1;NONCE;SEQUENCE;KIND;HEX... BEL`. NONCE is 128
random bits per connection; sequence numbers increase monotonically. Each field
is hex-encoded UTF-8/surrogate-preserving data. Ordinary output is never decoded.
Malformed/stale/unknown/oversized and unrelated terminal sequences pass through.
Nonces prevent accidental collisions, not attacks by a destination process with
PTY access. No additional listener, forwarding permission or remote agent is required.

Kinds and field order:

```text
HELLO(host,user,cwd,session,shell)
REQUEST(request,key,line,point,mark,keymap,host,user,cwd,session,workspace)
HANDOVER(request,typeahead[,pending_hex])
START(command_id,command,host,user,cwd,session,remote_time)
END(command_id,status,remote_time)
PROMPT(cwd), DEGRADED(reason), BYE
ABORT(request,session), RELEASE(request,session)
BUNDLE_REQUEST(session), BUNDLE_HANDOVER(session,pending_hex), BUNDLE_ABORT(session)
```

Session/request IDs identify input generations; stale results cannot edit later
buffers. Workspace is the destination's nearest `.git` ancestor. NUL is outside
Bash string representation; queued BLE pending bytes use binary-preserving hex.

| Bound | Value |
| --- | --- |
| Complete frame | 1 MiB |
| Command/query/selection | 256 KiB UTF-8; reject/cancel rather than truncate |
| Shell typeahead | 64 KiB |
| Idle suggestion prefix/result | 4 KiB / 64 KiB, single-line/control-free |
| Background output while UI active | 1 MiB, then stop backend reads |
| Editor archive / decoded transfer line | 8 MiB / 3072 bytes |

## Handover and return

A verified editor callback enters raw/no-echo and sends its authoritative
snapshot in REQUEST. The relay holds new front input and sends
`!NONCE:REQUEST:FENCE\n`. HANDOVER returns previously sent typeahead. The relay
feeds recovered and held bytes only after native READY, avoiding consumption by
terminal negotiation. Outstanding native terminal-query replies are handled separately.

The exact result file uses `__atuin_insert__:` / `__atuin_accept__:`; empty output
cancels. Strip exactly one tag. Return lines are `!NONCE:REQUEST:DATA:HEX\n`
(at most 1024 hex characters), followed by
`!NONCE:REQUEST:DONE:insert|accept|cancel\n`. Command data is never evaluated or
injected as raw command-plus-newline. The editor validates identity/bounds,
restores buffer/cursor on cancel and acknowledges RELEASE before new input flows.

Fence timeout is 30 s, relay handover 35 s and native READY 5 s. A waiting
callback sends ABORT while retaining terminal ownership; the relay sends one
cancel and ignores stale aborts after RELEASE. UI interaction has no idle timeout.
UI failure cancels; uncertain transport loss never triggers command replay.

## Bundle startup

BUNDLE_REQUEST saves tty modes and takes ownership. An ordered
`!NONCE:BUNDLE:FENCE\n` and BUNDLE_HANDOVER recover old input before transfer.
Base64 DATA ends with `!NONCE:BUNDLE:END:SIZE:SHA256\n`; receiver checks exact
size/hash before extracting validated regular files into a private directory.
Editor HELLO releases held input. A premature HELLO closes the owned connection.

Malformed transfer drains to END. Timeout emits BUNDLE_ABORT while retaining tty
ownership until ordered zero-size/zero-hash abort END or EOF. After normal END
has been queued, startup failure closes the owned transport rather than injecting
another line into a possibly active editor. Main-shell unload removes owned files;
exec/SIGKILL/power loss can leave them. Runtime editor downloads are disabled.

Concurrent output can corrupt an in-band frame. Invalid bytes pass through and
the exchange times out; perfect framing against hostile writers is not claimed.
Severe interleaving and broader disconnect cases remain acceptance gates in STATUS.md.
