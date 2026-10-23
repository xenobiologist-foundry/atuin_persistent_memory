# Loaded once after the ordinary hub login startup files.
[[ $- == *i* ]] || return 0
[[ ${_ATUIN_SSH_HUB_INITIALIZED:-0} == 1 ]] && return 0
_ATUIN_SSH_HUB_INITIALIZED=1
# sshd creates a fresh login environment rather than inheriting Docker's LANG.
# Supply a Unicode-capable default without overriding client/profile choices.
export LANG="${LANG:-C.UTF-8}"
export ATUIN_HOME=/state/atuin
export ATUIN_CONFIG_DIR=/state/atuin
export ATUIN_SSH_STATE_DIR=/state/bridge
umask 077
# ble.sh provides the hub's inline editor suggestions. Load it before native
# Atuin so Atuin registers its own history source; destinations receive none
# of this bundle. Set ATUIN_SSH_HUB_AUTOSUGGEST=0 before login to opt out.
_atuin_ssh_blesh_loaded=0
if [[ ${ATUIN_SSH_HUB_AUTOSUGGEST:-1} != 0 && -t 0 && -t 1 ]]; then
    if source /usr/local/share/blesh/ble.sh --attach=none; then
        _atuin_ssh_blesh_loaded=1
    fi
fi
eval "$(atuin init bash --disable-ai)"
eval "$(atuin-ssh init bash)"
if [[ $_atuin_ssh_blesh_loaded == 1 ]]; then
    ble-attach
fi
unset _atuin_ssh_blesh_loaded
