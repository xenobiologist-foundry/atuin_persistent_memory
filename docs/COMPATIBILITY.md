# Linux hub compatibility

Recorded on 2026-10-24; this describes the implemented Linux image, not native
Mac acceptance. Results and outstanding gates are in [STATUS.md](STATUS.md).
Exact source/archive pins live in [build-pins.toml](../config/build-pins.toml),
`Dockerfile`, Cargo.lock and the ble.sh build recipe.

## Supported behavior and limits

| Surface | Implemented behavior / boundary |
| --- | --- |
| Runtime | Linux/amd64; Python 3.14.2, Bash 5.2.15, OpenSSH 9.2p1, official static-musl Atuin 18.24.1 and separate native compatibility binaries |
| Automatic remote entry | Configured Bash 5+ login shell; unsupported account shells remain plain |
| Explicit remote entry | `atuin-ssh connect --bash -- target` selects existing Bash 4.4+; 4.4 needs numeric `date '+%s %N'` |
| Temporary ble.sh | Default; existing tar, base64 decoding, awk, stty, mktemp and supported SHA256 tools required; receiver checks prerequisites |
| Editor fallback | Nonempty PROMPT_COMMAND, existing editor/debug hooks or missing bundle prerequisites retain GNU Readline; explicit `--no-autosuggest` supported |
| Native UI | Insert/accept/cancel, Unicode/cursor/mark, vi/emacs, Up-specific scope, first-prompt and burst input exercised in real PTYs |
| Search context | ACCOUNT is exact host/account; HOST spans accounts; directory/workspace qualify host/account; GLOBAL removes identity predicates, while native shell filtering still applies |
| Hostname collisions | Registered endpoint guard holds capture pending/refuses ambiguous ACCOUNT; historical/imported/unregistered overlap remains unresolved |
| Native state | Upstream APIs and encrypted record machinery; migration/version checks, stable-ID replay, tombstones, privacy and concurrent bridge writers tested; daemon refused |
| Import | Configured HISTFILE, timestamps, multiline/Unicode, repeated occurrences, dry-run, append/overlap and explicit resume; broader ambiguity/rotation/bounds remain gates |
| Foreground apps | read/password, cat, jobs, external editor, less/nano/top, resize and output backpressure tested; wider applications/keymaps remain gates |
| SSH | Aliases, RemoteCommand/explicit commands and status, TCP forwarding, ProxyJump and ControlMaster ownership tested; broader auth/escape combinations remain gates |
| Nested shells | sudo/su/SSH/container/tmux foreground passthrough; inner capture/context is outside scope |
| Deployment | Installed image, recreation and stopped-state restore tested; current interactive Windows, native Linux Engine and physical LAN verification remain open |

Configured HISTFILE and normal destination Bash history writes remain intact.
Hooks changed after initialization can disable capture. Incompatible DEBUG or
functrace is preserved, with enhancement disabled. Startup uses scalar prompt
hooks through Bash 5.0 and native array execution from 5.1. Readline's vi-insert
keymap is used. Arbitrary existing preexec/EXIT/Atuin combinations need more evidence.

## Reproduce

From the root, run Linux execution in disposable containers:

```sh
./scripts/hub.sh test
# Windows PowerShell: ./scripts/hub.ps1 test
```

This runs the installed modern PTY/native suite, offline attempted-egress probes
and independent non-root SSH import. For the actual Bash 4.4.23 fixture:

```sh
docker compose -f compose.test.yaml -f compose.legacy-test.yaml build
docker compose -f compose.test.yaml -f compose.legacy-test.yaml up -d --wait hub destination
docker compose -f compose.test.yaml -f compose.legacy-test.yaml run --rm client
docker compose -f compose.test.yaml -f compose.legacy-test.yaml down
```

Fixture projects have separate keys/volumes; `down` keeps volumes. Legacy Bash
is GNU 4.4.18 plus official patches 019–023, with pins in
`docker/bash44-sources.sha256`. Its account uses `/bin/sh`, no Python or Atuin;
the client explicitly selects Bash. Tests must never mount personal history.

Useful native probes in a disposable image:

```sh
docker run --rm --entrypoint atuin atuin-ssh:local init bash
docker run --rm --entrypoint atuin atuin-ssh:local search --help
docker run --rm --entrypoint python atuin-ssh:test tests/reproduce_duplicate_hostname.py
```

The duplicate-hostname probe bypasses the live guard and demonstrates native
representation overlap using synthetic data; it is not a physical two-host test.
For manual UI probes, use fresh ATUIN_HOME and exact result files, avoiding shell
substitution that strips trailing newlines. Private result protocol 2 tags both
insert and accept; commands beginning with literal tags retain their meaning.

## Relevant native source decisions

Pinned Atuin 18.24.1's interactive search does not apply the noninteractive
author/shell CLI filters. Set `search.shells` in config for the TUI. Its HOST
scope spans users, directory scope is path-only, and Git discovery is local.
These differences require the separate native ACCOUNT/path/workspace extension.
Stock official Atuin remains available and its database schema stays unchanged.

ble.sh is pinned to `ble-nightly-20260908+d81fd54`; its disabled-updater bundle
is 3,799,040 bytes, SHA256
`63a0c475827efb41f8156a28b8e057749c28f03fc4cc9b5989e86b204ee945ee`.
Normal unload cleans owned files; exec/SIGKILL/power loss may leave them. Separate
remote-editor egress observation and broader editor parity remain open.

Measurements and their methodology are in [BENCHMARKS.md](BENCHMARKS.md);
operator configuration and recovery are in [OPERATIONS.md](OPERATIONS.md).
