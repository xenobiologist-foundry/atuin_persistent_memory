# Mac transport and ownership

The copied Python core retains the pinned protocol: bounded nonce/sequence OSC
frames, WAIT/HANDOVER fences, READY after native negotiation and a complete first
frame, then RELEASE into the same editor. A relay has one input owner: OpenSSH,
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
