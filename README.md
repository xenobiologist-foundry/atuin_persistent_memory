# Atuin SSH shell hub

A **workstation** SSHs into the persistent Linux **hub**. Ordinary `ssh target`
inside the hub starts the real OpenSSH client and temporarily instruments the
**destination** Bash. Up and Ctrl-R run native Atuin on the hub and return the
selection to that destination's editor. Destination completion, editing and
execution remain remote. Nothing is permanently installed on the destination.

By default, eligible sessions load the hub's pinned ble.sh bundle into a private
temporary destination directory for inline Atuin history suggestions. The
destination does not need Atuin, Python, a package install or Internet downloads.
Its editor queries native history on the hub using its actual host/account.
This session editor replaces GNU Readline while keeping editing and completion
on the destination. Use `atuin-ssh connect --no-autosuggest -- myserver` to retain
the previous GNU Readline integration without destination project files.

Native Atuin history, records, keys, configuration and bridge recovery metadata
live in local Docker named volumes. There is no Atuin account, sync server or
external history/AI service. A central LAN hub shares its local history across
workstation sessions. Separate hubs have separate histories.

This is software under development. See [acceptance status](docs/STATUS.md) for
passed tests and remaining MVP gates. Running Atuin in the hub alone does not
establish onward SSH correctness.

## Windows quickstart

Use Docker Desktop with Linux containers, PowerShell and Windows OpenSSH. No
separately maintained WSL distribution or native Windows Python is required.
The Docker Desktop backend and Windows host must stay running.

```powershell
# Use your existing public key. Never supply a private key here.
./scripts/hub.ps1 setup -PublicKey "$HOME/.ssh/id_ed25519.pub"
docker compose build
docker compose up -d
ssh -p 2222 hubuser@localhost
```

If needed, generate a workstation SSH key using `ssh-keygen -t ed25519` first.
For a custom key name, pass the matching **private** filename to the SSH client.
For example, if setup used `atuin_hub_ed25519.pub`, connect with:

```powershell
ssh -i "$HOME/.ssh/atuin_hub_ed25519" -p 2222 hubuser@localhost
```

The `.pub` file authorizes the key on the hub; it is not the client identity file.
Check the hub's host fingerprint against
`docker compose exec hub ssh-keygen -lf /state/sshd/ssh_host_ed25519_key.pub`
before accepting it. The image never contains authorized keys or private state.

## Linux quickstart

```sh
./scripts/hub.sh setup "$HOME/.ssh/id_ed25519.pub"
docker compose build
docker compose up -d
ssh -p 2222 hubuser@localhost
```

The image is Linux/amd64. Native Linux Docker Engine execution is a separate
manual verification gate until recorded in the acceptance status.

## Destination credentials and daily use

Automatic enhancement uses the destination's configured Bash login shell and
**Bash 5 or later**. For an account configured with `/bin/sh`, or one using
**Bash 4.4**, explicitly select its existing Bash for this session from the hub:

```sh
atuin-ssh connect --bash -- myserver
```

This requires Bash 4.4 or newer; Bash 4.4 also needs the existing `date` utility
to support `+%s %N`. The account's configured shell and profiles are not changed.
Ordinary `ssh` preserves unsupported account shells. Starting a nested Bash
later does not install the session integration.

Inline suggestions are enabled for supported packaged-hub connections. To
select them explicitly, use `atuin-ssh connect --autosuggest -- myserver` (add
`--bash` for an account whose configured shell is not compatible Bash). Type a
history prefix, press Right Arrow to insert the gray suggestion, then Enter to
execute. Tab completes destination files and commands. Up/Ctrl-R open native
Atuin on the hub. Set and export `ATUIN_SSH_REMOTE_AUTOSUGGEST=0` in the hub shell
to keep GNU Readline by default; explicit `--autosuggest` overrides it.

Each enhanced connection transfers about 3.8 MB of pinned editor files from the hub
over the existing encrypted SSH stream. Existing destination `tar`, `base64 -d`,
`awk`, `stty` and a supported SHA256 utility are required. Missing prerequisites
fall back to the ordinary Bash integration. Editor files, caches and runtime
state stay in a private session directory under the destination's `TMPDIR` or
`/tmp`; normal logout removes it. Process replacement with `exec` or abrupt
process loss can leave temporary files.
No destination profiles are changed. Existing editor/debug hooks or nonempty
`PROMPT_COMMAND` hooks use GNU Readline mode. This preserves their startup input
and avoids ble.sh reusing the main prompt inside foreground `read -e`.
The ordinary `ssh` wrapper forwards the hub's native disabled-binding choices.
For a direct `atuin-ssh connect` invocation, export
`ATUIN_SSH_DISABLE_CTRL_R=1` or `ATUIN_SSH_DISABLE_UP=1` to disable those bindings.

At the hub prompt, create a dedicated outbound key with `ssh-keygen -t ed25519`.
Add its public key to the destination account through your usual authorized
administration process. Keep its private key in the hub's persistent `~/.ssh`
with mode 600. Configure aliases in `~/.ssh/config` normally, for example:

```sshconfig
Host myserver
    HostName server.example.net
    User myaccount
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Then use `ssh myserver`, normal Up/Ctrl-R, Tab to insert, Enter to accept
according to native `enter_accept`, or Escape to cancel. Atuin runs on the hub.
No special prefix or separate search command is needed. Host-key checking and
authentication remain OpenSSH's responsibility. Agent forwarding is optional
and must be explicitly requested; it is not enabled by the project.

`/usr/bin/ssh myserver` bypasses enhancement. So does `ATUIN_SSH_PLAIN=1 ssh
myserver`. Explicit remote commands, SFTP/SCP, forwarding-only sessions, config
queries and unsupported invocations retain ordinary OpenSSH behavior. An
existing `ssh` shell function is preserved; use `atuin-ssh connect -- myserver`
explicitly in that case. `atuin_ssh_disable` removes the installed wrapper;
`atuin_ssh_enable` enables it again.

The hub initializes native Atuin with `--disable-ai`. Configuration begins from
[config/atuin.toml](config/atuin.toml), copied only when the persistent config is
absent. Edit `/state/atuin/config.toml` as the hub user to customize native search.
Keep `auto_sync=false` and `update_check=false`. Existing customization survives
restart. Do not import login credentials or attach cloned native writer state to
two running independent hubs. Daemon search is currently disabled and requires
separate compatibility verification.

The hub's Bash also shows inline suggestions from its native Atuin history,
using ble.sh and Atuin's own history source. Type a command prefix, then press
**Right Arrow** to insert the suggested suffix; **Enter** executes the completed
line. Up and Ctrl-R still open native Atuin. Suggestions use the current native
search scope, so the default HOST scope at the hub can hide destination history.
The destination mode uses a separate temporary editor with the destination's
context; the hub prompt keeps its own context and native history scope.

SSH logins use `LANG=C.UTF-8` when `LANG` is unset or empty, preserving explicit
client/profile locale settings. A first-use `tput cache ... done` notice from
ble.sh means it successfully generated its terminal cache.

To disable inline suggestions, put `export ATUIN_SSH_HUB_AUTOSUGGEST=0` in the
hub user's `~/.bashrc` **before** its `/etc/atuin-ssh/hub.bash` source line, then
reconnect. The bundled ble.sh version is pinned and updated through image builds;
`ble-update` does not download or install anything.

## Troubleshooting an onward session

A normal destination prompt after `ssh myserver` is expected. Press **Up** or
**Ctrl-R** at that prompt to open native Atuin; the interface is displayed only
while searching. A successful login alone does not prove that enhancement loaded.

Check the destination's existing shell and Bash version:

```sh
printf 'Login shell: %s\n' "$SHELL"
command -v bash
bash --version
```

Ordinary `ssh` preserves a non-Bash login shell. Use the explicit `--bash` form
above to select an existing compatible Bash. A Bash 4.4.23 destination with a
`/bin/sh` account originally stayed plain; that report prompted the explicit
compatibility path. A separate Bash 5.2.21 destination passed user-confirmed
Ctrl-R and capture. These checks do not install anything; the integration remains
session-only on the destination.

At the actual **hub prompt**, `type -t ssh` should report `function` for the
installed wrapper. Run `atuin-ssh doctor` there to check the interactive session.
An existing custom `ssh` function may be preserved instead; try
`atuin-ssh connect -- myserver` in that case. The PowerShell/Linux helper's
`doctor` action runs noninteractively, so its `tty`, `native_integration` and
`ssh_wrapper` fields can correctly be `false` even when an interactive login works.

History captured on a destination is stored with that destination's account and
host context. Native search opened at the hub defaults to the hub's **HOST**
scope, which can hide those remote entries. To inspect all local native history
from the hub, open:

```sh
atuin search -i --filter-mode global
```

The onward widget uses its remote context automatically. If Up/Ctrl-R still use
ordinary Bash history, retain the exact `atuin-ssh:` notice and sanitized doctor
output. Custom Readline bindings, incompatible DEBUG hooks, another nested shell
or a login profile replacing the bootstrap hook can prevent enhancement. Do not
share history databases, terminal transcripts, private keys or full environments
when reporting the problem.

## Development and verification

```powershell
./scripts/hub.ps1 test
./scripts/hub.ps1 doctor
# Optional editable source; independently named development volumes
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

Tests use actual Linux PTYs, installed Python 3.14 code, native Atuin and real
workstation → hub sshd → destination sshd connections. They run in containers.
The disposable fixture project is `atuin-ssh-test`, distinct from production.
No ordinary stop/rebuild command removes named volumes. Test artifacts contain
only disposable fixture data. Never point integration tests at personal history.

## Import, diagnostics and operations

At the hub:

```sh
atuin-ssh doctor
atuin-ssh history import --target myserver --dry-run
atuin-ssh history import --target myserver --max-entries 10000 --max-bytes 8388608
atuin-ssh history retry --timeout 10
atuin-ssh history resume-imports
```

Import discovers this account's configured `HISTFILE` using login Bash startup;
it never executes history content or flushes another shell's in-memory history.
Timestamp delimiters preserve multiline records. Untimestamped multiline files
are explicitly ambiguous; synthetic ordering timestamps and unknown metadata
are identified in the provenance ledger. Repeat imports align occurrences,
including repeated equal commands, rather than deduplicating command text.
Unresolvable native uniqueness collisions remain pending. Review dry-run
limitations and [compatibility](docs/COMPATIBILITY.md) before bulk imports.
Keep the same time bounds and privacy settings when relying on occurrence
alignment: narrowing and later widening the accepted snapshot can lose earlier
alignment, particularly for entries without original timestamps.
Use the same `--target` spelling too: different SSH aliases currently identify
separate import sources, even when they reach one machine. Untimestamped entries
can duplicate in that case. Timestamped native uniqueness conflicts stay pending.
The native records retain the destination's actual hostname and account. Import
is explicit; connecting does not automatically scan a destination's old history.

Progress appears on stderr during reading, privacy checks, preflight and native
writes; stdout contains the final JSON report. Ctrl-C stops the operation with
exit status 130 and retains completed writes and privacy-approved pending work.
Run `atuin-ssh history resume-imports` explicitly to continue saved work without
another SSH connection or password prompt. An interrupted native write is checked
by its original stable ID before retrying. Recovery also honors native deletions.
An earlier version could import silently for a long time and show non-TTY Bash
job-control warnings; rebuild the image to get progress and the faster batch path.

To apply a source update from the repository, run `docker compose up -d --build`.
Recreating the hub disconnects active SSH sessions. Reconnect afterward and run
`atuin-ssh history resume-imports` to continue an interrupted import from its
saved ledger; it does not fetch the destination history again.

With `store_failed=false`, unknown historical outcomes are pending without a
locally retained command payload. Importing them requires an explicit policy
change and another fetch; no historical success status is invented. Live
commands under this setting stay in bounded RAM until successful completion,
so incomplete commands can be lost without ever entering a durable payload.

`doctor` returns sanitized JSON without command bodies, terminal transcripts,
credentials or full environments. Redirect that JSON to make a diagnostic
bundle. Also retain version, image digest and relevant failure messages. Do not
attach databases or `.ssh` contents to public reports.

```powershell
./scripts/hub.ps1 stop
./scripts/hub.ps1 start
./scripts/hub.ps1 backup -BackupDirectory "D:/Backups/Atuin hub"
# Restore requires a stopped fresh project's volumes.
./scripts/hub.ps1 restore -Project atuin-ssh-moved -Archive "D:/Backups/Atuin hub/hub.tar.gz"
```

Linux equivalents use `scripts/hub.sh`. Backup stops all hub writers and copies
the complete state and home, including record store, metadata, native local
keys, outbox, SSH server identity and user files. Protect the archive as a secret:
it can contain history and outbound private keys. Native SQLite is not encrypted
at rest by these settings; use host disk encryption and encrypted backup storage
when appropriate. Moving a stopped hub preserves its writer identity; starting
a separate independent hub requires fresh volumes. Back up before upgrades;
an older image may not understand databases migrated by a newer version.

## Local and LAN layouts

The default `.env` binds `127.0.0.1:2222`. For a central hub, set `HUB_BIND_ADDRESS`
to the Docker host's selected LAN interface address and keep a stable
`HUB_HOSTNAME`. Configure the host firewall to allow only the intended LAN
subnet and TCP port 2222. For example, an administrator can create a Windows
firewall inbound TCP rule restricted to that local address and `LocalSubnet`;
on Linux, restrict both the host firewall and Docker forwarding chain as
appropriate for that engine. Verify access from an authorized second machine
and rejection outside the boundary before considering LAN deployment verified.
Do not create router port forwarding or a public tunnel.

Other workstations use `ssh -p 2222 hubuser@LAN_HOST`. This published bridge port
does not give the container a DHCP identity or independent LAN IP. Destination
servers see the source selected by Docker/host routing. No host networking,
macvlan, privileged container or Docker socket is required.

Onward SSH, curl and Git retain normal networking. Diagnose LAN IP routing,
LAN DNS, public DNS/HTTPS and VPN routes separately; host `hosts` entries and
mDNS are not assumed to propagate into Docker. Configure Compose `dns:` only
when your network needs an explicit resolver. Docker Desktop provides
`host.docker.internal` for host services. No Linux host alias is required by
the baseline. History/search work without public internet once images are built;
a central hub still needs its workstation LAN connection and host available.

See [architecture and boundaries](docs/ARCHITECTURE.md),
[protocol](docs/PROTOCOL.md), [compatibility](docs/COMPATIBILITY.md), and
[continuation handoff](docs/HANDOFF.md).
