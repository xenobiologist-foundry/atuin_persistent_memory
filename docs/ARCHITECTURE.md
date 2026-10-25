# Linux hub architecture

```text
workstation terminal -> hub sshd -> hub Bash + native Atuin
                                    -> Python relay -> real OpenSSH -> destination Bash
                                         -> native Atuin TUI          + temporary ble.sh
```

The workstation supplies terminal input/output. The hub owns history, search and
coordination state. The destination owns editing, completion, command execution
and lifecycle callbacks. The separate native Mac application replaces the hub
with a local zsh entry layer; its source/build/runtime are self-contained.

## SSH and destination startup

`src/atuin_ssh/ssh.py` conservatively classifies invocations and evaluates config
with real `ssh -G`. Eligible interactive sessions use `/usr/bin/ssh` with argv
arrays. Commands, subsystems, forwarding-only/background/noninteractive sessions
and unsupported forms pass through. OpenSSH owns authentication, host keys,
proxies, jumps and multiplexing; the relay never kills a shared ControlMaster.

`bootstrap.py` and `bash/remote.bash` deliver session-only Bash integration through
a startup descriptor. POSIX ENV startup restores ordinary Bash modes, the original
ENV and history defaults, then sources login profiles and composes their final
scalar/array PROMPT_COMMAND before its first execution. sshd's command-launching
Bash can separately run noninteractive `.bashrc`; arbitrary startup equivalence
is not established. POSIX/readonly ENV/unavailable descriptor cases stay plain.
Incompatible DEBUG/functrace is preserved and enhancement degrades.

Default destination editing uses pinned ble.sh transferred over the same SSH
stream. The validated regular-file archive is checked for size/hash and extracted
under a private session directory. No destination downloads, profile edits or
system installation occur. Nonempty prompt hooks, existing editors and missing
prerequisites retain GNU Readline. `--no-autosuggest` selects that mode explicitly.
Normal main-shell unload removes temporary files; exec/hard loss may leave them.

BLE uses lifecycle hooks and a narrowly pinned decoder/unload shim. Suggestions
use native ACCOUNT prefix search on the hub; a bounded read-only lookup by native
UUID preserves exact text. New typing cancels stale replies. No second search
store is introduced.

## Terminal ownership

`relay.py` owns the front terminal, backend SSH PTY and temporary native UI PTY.
Only one input consumer is active. A callback REQUEST carries authoritative
buffer/cursor/keymap/context; fenced HANDOVER recovers typeahead. Native READY
follows terminal negotiation and the first result frame. RELEASE acknowledges
restored editor ownership. See [PROTOCOL.md](PROTOCOL.md) for wire details.

Ordinary bytes are forwarded unchanged, with bounded queues and partial writes.
Background output during search buffers to 1 MiB, then backpressures backend
reads. Resizes reach both PTYs. Ctrl-C/Z/D remain destination input; local SSH
suspension restores front terminal modes first. Catchable exits restore termios
and file flags. Hard process loss cannot guarantee restoration. There is no
automatic reconnect or command replay.

## Native history and identity

The official Atuin executable remains unchanged. Distinct pinned components
reuse upstream APIs: `atuin-ssh-native` handles privacy/write/reconciliation;
`atuin-ssh-search` adds ACCOUNT and host/account-qualified path/workspace scopes
to the real TUI. GLOBAL removes those identity predicates; shell filtering is
independent. Remote workspace comes from the destination, never a hub path.
Version and migration checks precede native write constructors. No native schema
or canonical history replacement is introduced. See [native helper](../native-helper/README.md).

Commands retain actual execution host/account, pre-command cwd and unique shell
session IDs. Alias/effective endpoint provenance is separate from native origin.
Registered conflicting endpoints with the same hostname/account cause allowed
captures to remain `pending_identity` and refuse misleading ACCOUNT search.
Old native/imported/unregistered rows are outside that guard. Complete machine
mapping remains unresolved; aliases do not establish distinct native identities.

Bash 5 uses EPOCHREALTIME; explicit Bash 4.4 uses fractional `date`. Duration is
remote wall-time completion minus start, including instrumentation; reversal
becomes unknown. Background status means launch status. Exit/exec/disconnect
never imply success. Duplicate fallback capture respects HISTCONTROL/HISTIGNORE;
complex escaped/bracket/extended HISTIGNORE patterns conservatively degrade it.

## Persistence, import and privacy

`history.py` moves events through bounded RAM, native privacy checks and a private
durable outbox. A worker serializes cooperating writers, preserves stable UUIDs
and reconciles uncertain commits against native records/tombstones. A bounded
visibility barrier makes healthy completed writes searchable at the next prompt.
Storage failures report pending work while leaving SSH usable. Events lost before
durable local acceptance cannot be recovered.

With `store_failed=false`, up to 128 commands/16 MiB remain volatile until success.
Failed/unknown outcomes never become durable command bodies; imported unknown
outcomes remain pending without payload. No terminal/password/output transcript
is recorded. Account/sync/update/telemetry/AI services are not provisioned.

`importing.py` reads configured Bash HISTFILE through a separate real SSH PTY,
restoring raw mode after profiles. Privacy precedes durable occurrence-ledger
payloads. Native batches hold at most 64 entries/1 MiB JSON; coordinator locks and
durable attempts support explicit stable-ID resume. Unknown fields stay unknown.
Target aliases, policy/bounds changes and ambiguous rotations limit alignment.

One hub shares one local native store across workstation sessions. Independent
hubs remain independent. SQLite stays on local Linux-backed storage, not SMB/NFS
or Windows checkout mounts. Backups quiesce all writers and preserve full state;
never activate independent clones of one writer identity.
