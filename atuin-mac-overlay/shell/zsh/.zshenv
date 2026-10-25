# Read the normal startup file exactly once with its normal ZDOTDIR value.
if [[ $ATUIN_LAYER_ZDOTDIR_WAS_SET == 1 ]]; then
    export ZDOTDIR=$ATUIN_LAYER_USER_ZDOTDIR
else
    unset ZDOTDIR
fi
[[ ! -r ${ZDOTDIR:-$HOME}/.zshenv ]] || source "${ZDOTDIR:-$HOME}/.zshenv"
typeset -g _alo_user_zdotdir=${ZDOTDIR:-$HOME}
typeset -g _alo_user_zdotdir_set=${+ZDOTDIR}
export ZDOTDIR=$ATUIN_LAYER_STARTUP
