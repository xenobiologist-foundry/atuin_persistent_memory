if (( _alo_user_zdotdir_set )); then
    export ZDOTDIR=$_alo_user_zdotdir
else
    unset ZDOTDIR
fi
[[ ! -r ${ZDOTDIR:-$HOME}/.zshrc ]] || source "${ZDOTDIR:-$HOME}/.zshrc"
_alo_user_zdotdir=${ZDOTDIR:-$HOME}
_alo_user_zdotdir_set=${+ZDOTDIR}
# Activate at the first prompt, after the user's .zlogin as well.
autoload -Uz add-zsh-hook
_alo_first_prompt() {
    add-zsh-hook -d precmd _alo_first_prompt
    source "$ATUIN_LAYER_ROOT/shell/local.zsh"
    unfunction _alo_first_prompt
}
add-zsh-hook precmd _alo_first_prompt
export ZDOTDIR=$ATUIN_LAYER_STARTUP
