# Atuin SSH middleware

Search and record remote Bash commands with native Atuin while keeping editing,
completion and execution on the destination. OpenSSH handles connections and
authentication; destinations need no Atuin or Python installation.

| Runtime | Start here |
| --- | --- |
| Native Apple Silicon Mac: local zsh plus enhanced SSH | [Mac setup](atuin-mac-overlay/README.md) |
| Persistent Linux Docker hub, entered over SSH from Windows/Linux/LAN clients | Instructions below |

History stays in the selected runtime's local store. Independent Macs and hubs
do not sync. No Atuin account or history server is required or provisioned.

## Start the Docker hub

Requires Docker Compose with Linux containers and an existing SSH key pair.
The image targets `linux/amd64`.

Linux:

```sh
./scripts/hub.sh setup "$HOME/.ssh/id_ed25519.pub"
docker compose build
docker compose up -d
ssh -p 2222 hubuser@localhost
```

Windows PowerShell, with Docker Desktop running:

```powershell
./scripts/hub.ps1 setup -PublicKey "$HOME/.ssh/id_ed25519.pub"
docker compose build
docker compose up -d
ssh -p 2222 hubuser@localhost
```

Setup copies the **public** key into `config/authorized_keys` and creates `.env`.
If using a custom key, give `ssh -i` its private filename. Verify the hub's host
fingerprint with `docker compose exec hub ssh-keygen -lf
/state/sshd/ssh_host_ed25519_key.pub` before accepting it.

## Connect to a destination

Inside the hub, configure outbound credentials in its persistent `~/.ssh` using
your usual OpenSSH workflow, then connect:

```sh
ssh my-server
atuin-ssh connect --bash -- legacy-server       # existing Bash 4.4+; also /bin/sh accounts
atuin-ssh connect --no-autosuggest -- my-server # GNU Readline instead of temporary ble.sh
/usr/bin/ssh my-server                         # plain SSH bypass
```

Automatic enhancement requires the destination's configured Bash 5+. Explicit
`--bash` selects an existing Bash 4.4+ for this session. Default suggestions use
a temporary 3.8 MB ble.sh bundle; profiles and system packages are left alone.
Unsupported shells/hooks fall back. See [compatibility](docs/COMPATIBILITY.md).

| Key at an enhanced prompt | Action |
| --- | --- |
| Ctrl-R / Up | Native Atuin search; Up defaults to SESSION |
| Tab in search / Enter / Escape | Insert / native accept / cancel |
| Right Arrow at the shell prompt | Insert the inline suggestion without executing |

Remote Ctrl-R starts in the destination host/account. To search all recorded
hosts **and shells** from the hub:

```sh
atuin config set search.shells all
atuin search -i --filter-mode global
```

## Configuration, history and updates

`.env` selects `HUB_USER`, `HUB_HOSTNAME`, `HUB_PORT` and `HUB_BIND_ADDRESS`.
Defaults are `hubuser`, `atuin-hub`, port `2222`, localhost only. For LAN access,
bind the Docker host's selected LAN address and restrict the port with its firewall.

Native config is `/state/atuin/config.toml`; `config/atuin.toml` seeds new state
only. Keep `auto_sync=false`, `update_check=false` and daemon mode disabled.
Named volumes hold native state in `/state/atuin/data/`, bridge metadata in
`/state/bridge/`, sshd keys in `/state/sshd/`, and the user's home separately.
Keep live SQLite on local storage.

```sh
# Inside the hub: import is explicit, connecting does not import old history.
atuin-ssh doctor
atuin-ssh history import --target my-server --dry-run
atuin-ssh history import --target my-server
atuin-ssh history resume-imports
```

Back up before upgrades. `./scripts/hub.sh backup /path/to/new-backup-dir` or
`./scripts/hub.ps1 backup -BackupDirectory "D:/Backups/Atuin"` stops writers,
copies complete state/home, then restores the previous running state.
Protect the archive: it includes history and may include private SSH keys.

Apply updates with `docker compose up -d --build` and reconnect; active SSH
sessions disconnect. `docker compose stop` preserves volumes. See
[operations](docs/OPERATIONS.md) for restore, import limits and troubleshooting.

## Development

Run `./scripts/hub.sh test` or `./scripts/hub.ps1 test` for disposable Linux
integration and privacy probes. Runtime/build pins are in
[config/build-pins.toml](config/build-pins.toml) and `Dockerfile`.

The core interaction works; full acceptance still has open identity, platform
and failure gates. See [status and TODO](docs/STATUS.md),
[architecture](docs/ARCHITECTURE.md), [protocol](docs/PROTOCOL.md) and
[benchmarks](docs/BENCHMARKS.md).
