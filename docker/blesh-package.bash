# The bundle is maintained by the container image, not the interactive shell.
_ble_base_package_type=atuin-ssh
function ble/base/package:atuin-ssh/update {
    printf '%s\n' 'ble.sh is pinned in this image; rebuild the image to update.' >&2
    return 1
}
