# Architecture and supported boundaries

The workstation is an ordinary SSH terminal. Hub sshd launches the persistent
non-root account's login Bash, native Atuin and reversible `ssh` function. For
eligible interactive calls the installed Python 3.14 package owns a front
terminal, a backend PTY running `/usr/bin/ssh`, and a temporary UI PTY running
the native Atuin binary. Python never parses or executes destination commands.
Destination Bash owns its editor, completion, accepted command representation,
execution and lifecycle callbacks.

The user selected temporary destination ble.sh on 2026-10-24 after comparing it
with a hub-side replacement editor. This explicitly extends the original brief's
GNU Readline/functions-only destination contract: the destination editor is
ble.sh for that session and its pinned modules/cache/runtime use private
temporary files. Native Atuin and all durable hub history remain on the hub.
The retained `--no-autosuggest` mode keeps the original GNU Readline behavior.

The hub validates a fixed, bounded, regular-file-only editor archive and sends
it over the existing SSH stream. A raw-terminal fence recovers prior typeahead
before transfer; the relay holds new input until editor startup is acknowledged.
The destination checks exact size and SHA256 before extraction and sources the
bundle after ordinary login profiles. It does not fetch software, modify user
startup files or install system packages. Ordinary exit cleans owned session
files; hard process loss may leave a private temporary directory.

Destination BLE widgets send authoritative line/cursor/keymap/context snapshots
through the fenced protocol. Idle prefix requests use a bounded background
native search on the hub with exact ACCOUNT scope. New typing cancels stale
suggestions; replies are consumed only while the editor owns its channel.
Up/Ctrl-R retain the actual hub-native TUI and its insert/accept/cancel results.
BLE lifecycle hooks capture commands/status/cwd without competing DEBUG traps.

The destination receives Bash functions, variables, hooks and bindings through
an SSH command and an initialization file descriptor. A real login Bash uses
POSIX ENV startup to read that descriptor, restores ordinary Bash modes and the
original exported ENV, closes the private descriptor, then reads `/etc/profile`
and the first readable user login profile. The payload composes the profiles'
final PROMPT_COMMAND before its first execution, so the first primary Readline
prompt is eligible without a warm-up command. The retained GNU Readline mode
creates no destination project files; the ble.sh mode adds only session files.
Existing POSIX startup or a readonly ENV falls back to ordinary Bash. Also,
sshd's command-launching Bash can run `.bashrc`
noninteractively before the login shell. A profile with noninteractive side
effects therefore needs differential startup verification. Full startup
equivalence for every custom profile is not established. Existing incompatible
DEBUG traps/functrace are left intact; capture and enhanced history keys degrade
to ordinary Bash behavior because foreground Readline eligibility cannot then
be proven. Changing
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

When native `store_failed=false` requires knowing the outcome first, accepted
commands remain in a bounded volatile queue until a successful completion.
Failed or unknown outcomes never enter a durable payload. This intentionally
loses incomplete commands on disconnect or process loss under that policy.
Imports with unknown historical outcomes are reported as pending without a
local command payload; changing the policy requires explicitly fetching again.

Connection provenance retains the SSH alias and a small allowlist of effective
endpoint fields beside the reported real hostname/account and native session.
It excludes full argv, ProxyCommand, credential paths and environments. This
metadata does not provide a verified machine identity. If observed effective
endpoints differ but report the same hostname/account, allowed captures are held
as `pending_identity` and the remote widget refuses a misleading ACCOUNT scope.
Aliases with the same effective endpoint share a group; HostKeyAlias remains
trust metadata, without manufacturing another endpoint. Different proxy routes
can conservatively require resolution even if they reach one machine. Older
unregistered/native/imported records remain outside this conflict detector and
can overlap in native scope. Full identity isolation remains an MVP gate; no
synthetic hostname conceals it.

Repeated commands suppressed by Bash's history number are captured from the
authoritative accepted buffer without changing HISTCONTROL. Complex escaped,
bracket or extended HISTIGNORE patterns conservatively disable this duplicate
fallback and report degradation; basic globs and exact `&` are supported.

Bash 5 supplies microsecond wall timestamps through `EPOCHREALTIME`. Explicit
Bash 4.4 sessions use the existing `date '+%s %N'` utility and normalize its
integer nanosecond component. Duration uses remote completion minus start,
including command execution and
shell instrumentation costs; it is not a monotonic clock. Clock reversal yields
native unknown duration (-1). Background status is launch status. `exit`,
`exec` and disconnect can leave unknown completion; no success is invented.
Historical import retains known timestamps and marks unknown/synthetic fields.

Explicit import reads the configured HISTFILE through a separate OpenSSH PTY.
Interactive Bash gets a controlling terminal; raw mode is applied again after
profiles so terminal newline conversion cannot alter file bytes. The reader
bounds startup output and history bytes and never executes file contents.
Native privacy, uniqueness probes and writes share setup in bounded batches
(64 entries and at most 1 MiB of JSON per batch). Privacy still precedes durable
ledger payloads. Oversized JSON for an otherwise valid command uses the existing
single-event wire limit. A coordinator lock prevents concurrent resume processes
from overwriting confirmed results with stale attempt states. Attempts are durable
before native submission; uncertain writes recover individually by stable ID,
including tombstones, before any replay. Progress uses counts, never command text.

One central LAN hub has one native local SQLite installation and writer state.
Concurrent workstation shells share that installation, with no Atuin account.
Availability follows the hub and workstation SSH connection. There is no
offline workstation cache or automatic merge between independent hubs. Keep
live SQLite on local Linux-backed storage, never SMB/NFS or a Windows source
bind mount. Back up complete stopped state before migration or upgrades.
