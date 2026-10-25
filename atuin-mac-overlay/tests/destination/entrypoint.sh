#!/bin/sh
set -eu
ssh-keygen -A >/dev/null
cp /fixtures/id_ed25519.pub /home/remote/.ssh/authorized_keys
chmod 700 /home/remote/.ssh
chmod 600 /home/remote/.ssh/authorized_keys
chown -R remote:remote /home/remote/.ssh
printf '%s\n' 'PS1="MAC-REMOTE> "' 'HISTFILE=/tmp/disposable-bash-history' > /home/remote/.bashrc
chown remote:remote /home/remote/.bashrc
exec /usr/sbin/sshd -D -e -o PasswordAuthentication=no -o PermitRootLogin=no -o AllowTcpForwarding=yes
