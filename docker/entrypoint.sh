#!/bin/bash
set -euo pipefail
umask 077
hub_user=${HUB_USER:-hubuser}
hub_home=$(getent passwd "$hub_user" | cut -d: -f6)
hub_group=$(id -gn "$hub_user")
[[ -n $hub_home && $hub_home == /home/* ]] || { echo 'Invalid hub account' >&2; exit 1; }
install -d -m 0711 /state
install -d -m 0700 /state/sshd
install -d -m 0700 -o "$hub_user" -g "$hub_group" /state/atuin /state/bridge "$hub_home/.ssh"
install -d -m 0700 -o "$hub_user" -g "$hub_group" /run/atuin-ssh
mkdir -p /run/sshd
if [[ ! -e $hub_home/.bash_profile ]]; then
    cp -a /etc/skel/. "$hub_home/"
    chown -R "$hub_user:$hub_group" "$hub_home"
fi
if [[ ! -e /state/atuin/config.toml ]]; then
    config_source=/usr/share/atuin-ssh/config.toml
    [[ ! -f /run/config/atuin.toml ]] || config_source=/run/config/atuin.toml
    install -m 0600 -o "$hub_user" -g "$hub_group" "$config_source" /state/atuin/config.toml
fi
# Enforce the no-account deployment contract without replacing user settings.
if ! python -c 'import pathlib,tomllib; c=tomllib.loads(pathlib.Path("/state/atuin/config.toml").read_text()); assert c.get("auto_sync") is False and c.get("update_check") is False'; then
    echo 'Atuin config must explicitly set root auto_sync=false and update_check=false.' >&2
    exit 1
fi
for key in ed25519 rsa; do
    if [[ ! -s /state/sshd/ssh_host_${key}_key ]]; then
        ssh-keygen -q -t "$key" -N '' -f "/state/sshd/ssh_host_${key}_key"
    fi
done
if [[ -f /run/keys/authorized_keys ]]; then
    install -m 0600 -o "$hub_user" -g "$hub_group" /run/keys/authorized_keys "$hub_home/.ssh/authorized_keys"
elif [[ ! -s $hub_home/.ssh/authorized_keys ]]; then
    echo 'Mount a public authorized_keys file at /run/keys/authorized_keys.' >&2
    exit 1
fi
if [[ ${ATUIN_SSH_TEST_KEYS:-} == /test-keys ]]; then
    install -m 0600 -o "$hub_user" -g "$hub_group" /test-keys/id_ed25519 "$hub_home/.ssh/id_ed25519"
    cp /state/sshd/ssh_host_ed25519_key.pub /test-keys/hub_host_ed25519.pub
    read -r key_type key_data _ < /test-keys/destination_host_ed25519.pub
    printf 'destination %s %s\n' "$key_type" "$key_data" > "$hub_home/.ssh/known_hosts"
    printf 'Host destination\n  User remote\n  IdentityFile ~/.ssh/id_ed25519\n  IdentitiesOnly yes\n  StrictHostKeyChecking yes\n' > "$hub_home/.ssh/config"
    chmod 0600 "$hub_home/.ssh/known_hosts" "$hub_home/.ssh/config"
    chown "$hub_user:$hub_group" "$hub_home/.ssh/known_hosts" "$hub_home/.ssh/config"
fi
chown -R "$hub_user:$hub_group" /state/atuin /state/bridge
chmod 0711 /state
chmod 0700 /state/atuin /state/bridge /state/sshd
# sshd starts a clean environment; interactive Bash sets these paths as well.
exec "$@"
