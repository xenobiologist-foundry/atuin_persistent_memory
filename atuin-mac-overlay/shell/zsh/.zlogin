if (( _alo_user_zdotdir_set )); then
    export ZDOTDIR=$_alo_user_zdotdir
else
    unset ZDOTDIR
fi
[[ ! -r ${ZDOTDIR:-$HOME}/.zlogin ]] || source "${ZDOTDIR:-$HOME}/.zlogin"
# Do not export the temporary startup directory into unrelated child shells.
unset ATUIN_LAYER_STARTUP ATUIN_LAYER_USER_ZDOTDIR ATUIN_LAYER_ZDOTDIR_WAS_SET
