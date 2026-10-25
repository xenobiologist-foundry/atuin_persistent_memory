#!/bin/bash
# Official upstream Bash 4.4.18 plus patches 019-023; test fixture only.
set -euo pipefail
build_root=/tmp/atuin-ssh-bash44-build
mkdir -p "$build_root"
cd "$build_root"
curl --fail --location --retry 3 https://ftp.gnu.org/gnu/bash/bash-4.4.18.tar.gz --output bash-4.4.18.tar.gz
for patch_number in 019 020 021 022 023; do
    curl --fail --location --retry 3 "https://ftp.gnu.org/gnu/bash/bash-4.4-patches/bash44-$patch_number" --output "bash44-$patch_number"
done
sha256sum --check --strict /tmp/bash44-sources.sha256
tar -xzf bash-4.4.18.tar.gz
cd bash-4.4.18
for patch_number in 019 020 021 022 023; do
    patch --batch --forward -p0 < "../bash44-$patch_number"
done
./configure --without-bash-malloc --disable-nls
make -j4
mkdir -p /out
install -m 0755 bash /out/bash44
/out/bash44 --version
[[ $(/out/bash44 -c 'printf %s "$BASH_VERSION"') == 4.4.23* ]]
