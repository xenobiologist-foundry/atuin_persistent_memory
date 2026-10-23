# Atuin SSH shell hub

A **workstation** SSHs into the persistent Linux **hub**. Ordinary `ssh target`
inside the hub starts the real OpenSSH client and temporarily instruments the
**destination** Bash. Up and Ctrl-R run native Atuin on the hub and return the
selection to that destination's existing Readline editor. Destination completion,
editing and execution remain remote. Nothing is installed on the destination.

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
