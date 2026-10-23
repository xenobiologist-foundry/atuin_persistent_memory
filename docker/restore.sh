#!/bin/bash
set -euo pipefail
archive=$1
[[ -d /restore/state && -d /restore/home && -f $archive ]] || exit 1
if [[ -n $(find /restore/state -mindepth 1 -maxdepth 1 -print -quit) || -e /restore/home/.ssh || -e /restore/home/.atuin-ssh-restored ]]; then
    echo 'Restore requires fresh state/home volumes; existing state is preserved.' >&2
    exit 1
fi
while IFS= read -r member; do
    case $member in
        state|state/|home|home/|state/*|home/*) ;;
        *) echo 'Unexpected archive member' >&2; exit 1 ;;
    esac
    case /$member/ in */../*|*/./../*) echo 'Unsafe archive member' >&2; exit 1 ;; esac
done < <(tar -tzf "$archive")
tar --numeric-owner -xzf "$archive" -C /restore
python "$(dirname -- "${BASH_SOURCE[0]}")/verify-restore.py" "$archive" /restore
touch /restore/home/.atuin-ssh-restored
echo 'Complete-state archive restored.'
