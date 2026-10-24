# Session protocol v1

The encrypted OpenSSH PTY carries terminal bytes and a small in-band protocol.
No listener, forwarding permission, remote Python or persistent agent is needed.
A separate channel would isolate rendering/control but would require additional
remote tooling or SSH forwarding/session assumptions. In-band framing preserves
the ordinary SSH deployment, at the cost of explicit bounds and fail-safe
degradation if concurrent output corrupts a frame. The nonce prevents accidental
collisions, not attacks by a hostile destination process with PTY access.

Frames are `ESC ] 777;atuin-ssh;1;NONCE;SEQUENCE;KIND;HEX... BEL`.
NONCE is 128 random bits per bridge connection. Each UTF-8/surrogate-preserving
field is hex encoded; ordinary output is never decoded. SEQUENCE is strictly
increasing. A shell has a random native session ID, monotonically numbered
command IDs and request IDs. Session+request identifies the current generation;
no response for a different request may edit Readline. v1 supports Bash string
data without NUL. Maximum complete frame is 1 MiB; malformed, stale, unknown,
oversized and unrelated terminal sequences pass through unchanged. A partial
prefix is retained only until it can be classified or exceeds the bound.

Kinds: HELLO(host,user,cwd,session,shell), REQUEST(request,key,line,point,mark,
keymap,host,user,cwd,session,workspace), HANDOVER(request,typeahead),
START(command_id,command,host,user,cwd,session,remote_time),
END(command_id,status,remote_time), PROMPT(cwd), DEGRADED(reason), BYE,
ABORT(request,session), RELEASE(request,session).
Temporary editor startup additionally uses BUNDLE_REQUEST(session),
BUNDLE_HANDOVER(session,pending_hex), BUNDLE_ABORT(session). These share the
same monotonic sequence with subsequent editor events. A BLE HANDOVER can use
three fields (request,hex,pending_hex), preserving NUL and arbitrary queued bytes.
Workspace is the nearest destination ancestor containing `.git`, discovered by
Bash filesystem tests. It is never inferred from a hub path. REQUEST supports
at most 256 KiB input; shell typeahead is bounded at 64 KiB.

State: authentication/bootstrap → instrumented shell → command running → prompt.
A verified Readline REQUEST, rather than a cached prompt flag or intercepted
key, enters widget wait. The callback saves termios, makes its tty raw/no-echo,
and sends the authoritative line, byte cursor, mark and keymap. The relay stops
forwarding front input and appends `!NONCE:REQUEST:FENCE\n` to backend input.
The callback drains all already-sent bytes through that fence, then returns
them in HANDOVER. The relay feeds those bytes and input held since REQUEST to
native Atuin on the UI PTY. Search/navigation then has no destination round trip.
The first handshake necessarily uses the hub-destination link; every UI key
still traverses the workstation-hub link.

## Temporary destination editor

When the packaged hub selects ble.sh, the destination first creates a private
session directory, saves tty modes, enters raw/no-echo and emits BUNDLE_REQUEST.
The relay holds new workstation input, moves unsent input into that held queue,
and sends `!NONCE:BUNDLE:FENCE\n`. The receiver returns all earlier input as
pending hex in BUNDLE_HANDOVER. Only then does the hub stream bounded base64 DATA
lines followed by `!NONCE:BUNDLE:END:SIZE:SHA256\n`. The receiver verifies the
expected build-time size/hash, extracts the validated regular-file-only archive,
restores tty modes and loads ble.sh after ordinary login profiles. HELLO from
the attached editor releases held typeahead. No executable code is delivered as
Readline input. A premature HELLO closes the owned SSH process rather than
releasing input over queued bundle data.

Malformed transfers drain through END. A receiver timeout emits BUNDLE_ABORT and
retains tty ownership until an ordered zero-size/zero-hash abort END or EOF. The
relay cancels its remaining bundle queue before acknowledging. After a normal
END has been queued, a startup deadline cannot safely send another protocol line
into a possibly active editor; it closes only the owned SSH connection instead.
The archive is bounded at 8 MiB; ordinary DATA lines carry at most 3072 decoded
bytes. Temporary directories, caches and runtime files are session-owned and
removed after normal BLE unload. `exec`, SIGKILL or power loss may leave them.

BLE editor widgets use the same fenced REQUEST/RELEASE exchange and the actual
hub-native TUI. A narrow compatibility shim for the pinned decoder transfers
its internally buffered raw input to the hub, including activation/query/Enter
bursts; it does not infer commands from terminal rendering. Command lifecycle
uses BLE PREEXEC/POSTEXEC hooks instead of competing GNU Readline DEBUG hooks.

REQUEST key `suggest` is an idle prefix lookup, without a TUI. A single bounded
worker invokes native exact-account prefix search on the hub. Native UUID output
selects the record; a bounded read-only query of its compatibility-checked native
history view retrieves exact text because native command formatting trims
whitespace. No SQL writes or separate suggestion database are used. Initial
automatic suggestions are single-line, control-free commands up to 64 KiB for
prefixes up to 4 KiB; native interactive history retains its larger multiline
contract. New typing cancels an idle reply, stale request IDs cannot edit later
input, and queued bytes return only after RELEASE. Ordinary typing always takes
priority over completing a suggestion.

The distinct native TUI writes `READY\n` to a private inherited pipe after its
first results frame and terminal negotiation. The relay holds recovered and new
user type-ahead until that notification. During negotiation it forwards only
responses to actual outstanding native CPR/device/keyboard queries. This
prevents startup from consuming a queued Enter/Tab or arrow as terminal setup
input. The pipe is not exposed to the destination and never carries history.
Failure to become ready within five seconds cancels the widget safely.

The exact result file distinguishes empty cancellation and `__atuin_accept__:`
acceptance. The isolated native extension adds `__atuin_insert__:` to insertion
results, including nonempty return-query results, under its private protocol
setting. Stripping exactly one action tag preserves commands literally starting
with either reserved string. The official stock binary remains unchanged.
Response lines are
`!NONCE:REQUEST:DATA:HEX\n` (up to 1024 hex characters each), followed by
`!NONCE:REQUEST:DONE:insert|accept|cancel\n`. The waiting callback validates
identity and bounds and decodes using Bash `printf -v`; command text is never
evaluated. Cancel leaves buffer/cursor/mark unchanged. Insert changes
READLINE_LINE/POINT. Accept uses native Atuin's two-step Readline macro pattern
to call `accept-line` after the callback; no raw selected-command/newline
injection occurs. Raw mode avoids canonical input line length truncation and
hex decoding preserves embedded and trailing newlines.

The callback emits RELEASE after consuming the result and restoring termios.
The relay holds front input until that acknowledgement. On a missing fence the
callback repeatedly requests ABORT while retaining tty ownership; the relay
sends one cancel response for that request and ignores stale repeated aborts
after RELEASE. No callback timeout returns to an ordinary shell while a late
result can still be in flight. A real corrupted-REQUEST test exercises the
30-second ABORT path and verifies the original editor survives without executing
queued type-ahead. Killing the native UI also restores the remote editor and
terminal modes. Broader severe interleaving remains a hardening gate.

Timeouts: callback fence 30s, relay handover 35s. UI interaction has no idle
timeout: the callback keeps ownership until matching DONE or terminal EOF so a
late result cannot enter an ordinary shell. UI process failure returns cancel.
A damaged or missing frame is never used to infer command
boundaries. Current recovery after severe stream desynchronization remains a
test/hardening gate; recover with plain SSH rather than assuming replay is safe.
Ordinary remote background output that interleaves inside a protocol frame can
invalidate it. v1 passes the invalid bytes through and times out; it does not
claim cryptographic source authentication or perfect framing against hostile
concurrent writers.
