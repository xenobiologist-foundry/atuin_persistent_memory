#!/bin/bash
set -euo pipefail
umask 077
mkdir -p /test-keys
if [[ ! -s /test-keys/id_ed25519 ]]; then
    ssh-keygen -q -t ed25519 -N '' -f /test-keys/id_ed25519
fi
chmod 0700 /test-keys
chmod 0600 /test-keys/id_ed25519
cp /test-keys/id_ed25519.pub /test-keys/authorized_keys
cat > /test-keys/ssh_config <<'CONFIG'
Host hub
    User hubuser
Host destination
    User remote
Host *
    IdentityFile /test-keys/id_ed25519
    IdentitiesOnly yes
    BatchMode yes
    StrictHostKeyChecking yes
    UserKnownHostsFile /test-keys/known_hosts
    LogLevel ERROR
CONFIG
