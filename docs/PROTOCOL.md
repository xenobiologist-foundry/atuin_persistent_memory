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

Atuin's exact result file distinguishes empty cancellation, insertion and
`__atuin_accept__:` acceptance. Response lines are
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
result can still be in flight. These recovery additions require a new integration
run; see the acceptance status for the Docker storage blocker.

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
