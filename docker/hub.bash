# Loaded once after the ordinary hub login startup files.
[[ $- == *i* ]] || return 0
[[ ${_ATUIN_SSH_HUB_INITIALIZED:-0} == 1 ]] && return 0
_ATUIN_SSH_HUB_INITIALIZED=1
export ATUIN_HOME=/state/atuin
export ATUIN_CONFIG_DIR=/state/atuin
export ATUIN_SSH_STATE_DIR=/state/bridge
umask 077
eval "$(atuin init bash --disable-ai)"
eval "$(atuin-ssh init bash)"
