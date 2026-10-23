# Architecture and supported boundaries

The workstation is an ordinary SSH terminal. Hub sshd launches the persistent
non-root account's login Bash, native Atuin and reversible `ssh` function. For
eligible interactive calls the installed Python 3.14 package owns a front
terminal, a backend PTY running `/usr/bin/ssh`, and a temporary UI PTY running
the native Atuin binary. Python never parses or executes destination commands.
Destination Bash owns Readline, completion, accepted command representation,
execution and lifecycle callbacks.

The destination receives Bash functions, variables, hooks and bindings via an
SSH command containing an exported first-prompt function and `exec bash --login
-i`. Profiles execute in the real login Bash; no rcfiles or other destination
files are created. A profile that replaces inherited `PROMPT_COMMAND` can
disable installation. Also, sshd's command-launching Bash can run `.bashrc`
noninteractively before the login shell. A profile with noninteractive side
effects therefore needs differential startup verification. Full startup
equivalence for every custom profile is not established. Existing incompatible
DEBUG traps/functrace are left intact and capture reports degradation. Changing
hooks after initialization can disable capture. These are acceptance gates,
not a claim of complete shell parity.

Only directly instrumented destination Bash is enhanced. `sudo -i`, `su`, a
second remote `ssh`, container shells and existing tmux/screen sessions remain
foreground terminal applications; inner commands are not attributed by
observing their prompts. The outer launch command is the only capture scope.
A future nested extension needs explicit new shell registration and its own
session IDs, authentication/transport policy, lifecycle and tests.

The relay forwards ordinary bytes unchanged. It removes only valid negotiated
control frames. One owner receives input: backend SSH, the handover callback,
or the native UI. Background backend output during UI activity is held up to
1 MiB and then backpressured by stopping backend reads. Normal byte ordering is
preserved on return. Every write handles partial progress; reads have bounded
queues. Resizes go to both active PTYs. Raw-mode Ctrl-C/Z/D are transport bytes
for the destination; the relay does not synthesize a second interrupt. Local
OpenSSH suspension restores the front terminal before suspending the relay.

Catchable exit/failure paths restore front termios and file flags. SIGKILL,
power loss and a dead relay cannot guarantee restoration: use a fresh terminal,
or type `stty sane` and `reset` if needed. A broken SSH connection never triggers
automatic reconnection or command replay. A lost transport cannot establish
whether a remote command completed.

The unmodified official `atuin` executable remains installed. Small separately
named version-pinned native compatibility components reuse upstream Atuin:
`atuin-ssh-native` for metadata-correct writes/privacy/reconciliation and
`atuin-ssh-search` for ACCOUNT search and remote directory/workspace context.
They do not introduce a substitute UI, native schema change, synchronization
service or canonical history database. Build sources and explicit upstream
patch anchors are in `native-helper/`. Incompatible migration checksums or
versions refuse native helper operations before write constructors run.

History starts and completions enter a bounded volatile queue. A background
worker runs native filters before writing a private durable outbox. Only
durably accepted events survive local process failure. Events not delivered
from the destination or lost before durable acceptance cannot be recovered.
The worker serializes cooperating bridge writers, uses stable native UUIDs and
reconciles native records after uncertain commits. Native search has a bounded
visibility barrier; delayed/pending writes are reported without killing SSH.
The outbox and occurrence ledger are implementation metadata, not a second
history search store.

Destination `EPOCHREALTIME` supplies microsecond wall timestamps. Duration uses
the observed remote completion minus start, including command execution and
shell instrumentation costs; it is not a monotonic clock. Clock reversal yields
native unknown duration (-1). Background status is launch status. `exit`,
`exec` and disconnect can leave unknown completion; no success is invented.
Historical import retains known timestamps and marks unknown/synthetic fields.

One central LAN hub has one native local SQLite installation and writer state.
Concurrent workstation shells share that installation, with no Atuin account.
Availability follows the hub and workstation SSH connection. There is no
offline workstation cache or automatic merge between independent hubs. Keep
live SQLite on local Linux-backed storage, never SMB/NFS or a Windows source
bind mount. Back up complete stopped state before migration or upgrades.
