#!/bin/bash
set -euo pipefail
umask 077
install -d -m 0700 -o remote -g remote /home/remote/.ssh
install -m 0600 -o remote -g remote /test-keys/id_ed25519.pub /home/remote/.ssh/authorized_keys
mkdir -p /run/sshd /state/sshd
for key in ed25519 rsa; do
    if [[ ! -s /state/sshd/ssh_host_${key}_key ]]; then
        ssh-keygen -q -t "$key" -N '' -f "/state/sshd/ssh_host_${key}_key"
    fi
done
cp /state/sshd/ssh_host_ed25519_key.pub /test-keys/destination_host_ed25519.pub
exec "$@"
