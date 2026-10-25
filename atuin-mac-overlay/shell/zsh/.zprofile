if (( _alo_user_zdotdir_set )); then
    export ZDOTDIR=$_alo_user_zdotdir
else
    unset ZDOTDIR
fi
[[ ! -r ${ZDOTDIR:-$HOME}/.zprofile ]] || source "${ZDOTDIR:-$HOME}/.zprofile"
_alo_user_zdotdir=${ZDOTDIR:-$HOME}
_alo_user_zdotdir_set=${+ZDOTDIR}
export ZDOTDIR=$ATUIN_LAYER_STARTUP
