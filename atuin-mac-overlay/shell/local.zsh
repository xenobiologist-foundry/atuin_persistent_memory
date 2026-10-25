# Native zsh/Atuin composition, installed before the first editable prompt.
[[ -o interactive ]] || return
autoload -Uz add-zsh-hook

# User startup may have adjusted PATH or configured a system Atuin. Application
# commands always resolve to this private installation; other PATH order stays.
path=("$ATUIN_LAYER_ROOT/bin" ${path:#$ATUIN_LAYER_ROOT/bin})
export PATH
export ATUIN_HOME=$ATUIN_LAYER_STATE/atuin
export ATUIN_CONFIG_DIR=$ATUIN_LAYER_STATE/config
export ATUIN_SSH_STATE_DIR=$ATUIN_LAYER_STATE/bridge
export ATUIN_AUTO_SYNC=false ATUIN_UPDATE_CHECK=false ATUIN_DAEMON__ENABLED=false
export ATUIN_AI__ENABLED=false ATUIN_PTY_PROXY__ENABLED=false
export ATUIN_DB_PATH=$ATUIN_HOME/history.db ATUIN_RECORD_STORE_PATH=$ATUIN_HOME/records.db
export ATUIN_KEY_PATH=$ATUIN_HOME/key ATUIN_META__DB_PATH=$ATUIN_HOME/meta.db
unset ATUIN_SESSION ATUIN_SHLVL ATUIN_HISTORY_ID ATUIN_PTY_PROXY_ACTIVE

# These names are pinned upstream hook names. add-zsh-hook's own deduplication
# plus removal prevents duplicate writers when a profile already initializes it.
add-zsh-hook -d preexec _atuin_preexec
add-zsh-hook -d precmd _atuin_precmd
add-zsh-hook -d zshaddhistory _atuin_zshaddhistory
typeset -a _alo_init_options=(--disable-ai)
[[ ${ATUIN_LAYER_DISABLE_CTRL_R:-0} != 1 ]] || _alo_init_options+=(--disable-ctrl-r)
[[ ${ATUIN_LAYER_DISABLE_UP:-0} != 1 ]] || _alo_init_options+=(--disable-up-arrow)
eval "$("$ATUIN_LAYER_ROOT/bin/atuin" init zsh "${_alo_init_options[@]}")"

# Upstream's asynchronous history end can race the next prompt/search or app
# exit. Use the same native hook API synchronously at this activation boundary.
_atuin_precmd() {
    local EXIT=$? __atuin_precmd_time=${EPOCHREALTIME-} duration=''
    [[ -n ${ATUIN_HISTORY_ID-} ]] || return 0
    if [[ -n $__atuin_preexec_time && -n $__atuin_precmd_time ]]; then
        printf -v duration %.0f $(( (__atuin_precmd_time - __atuin_preexec_time) * 1000000000 ))
        (( duration < 0 )) && duration=0
    fi
    "$ATUIN_LAYER_ROOT/bin/atuin" history end --hook --exit $EXIT ${duration:+--duration=$duration} -- "$ATUIN_HISTORY_ID" > /dev/null 2>&1
    export ATUIN_HISTORY_ID=''
}

if (( ! $+functions[_zsh_autosuggest_start] )); then
    source "$ATUIN_LAYER_ROOT/resources/zsh-autosuggestions/zsh-autosuggestions.zsh"
fi
# Native account search, including exact trailing spaces, supplies suggestions.
_zsh_autosuggest_strategy_atuin_layer() {
    suggestion=$("$ATUIN_LAYER_PYTHON" -I "$ATUIN_LAYER_ENTRY" atuin-layer suggest -- "$1" "$ATUIN_SESSION" "$PWD")
}
ZSH_AUTOSUGGEST_STRATEGY=(atuin_layer)

# Honor native filter_mode/search.shells and the separate Up/keymap options.
# Result files preserve trailing newlines and explicit insert/accept tags.
_atuin_search() {
    emulate -L zsh
    local saved_buffer=$BUFFER saved_cursor=$CURSOR saved_mark=$MARK saved_keymap=$KEYMAP
    local output result_file rc
    result_file=$(umask 077; command mktemp "${TMPDIR:-/tmp}/atuin-layer-result.XXXXXXXX") || return
    zle -I
    ATUIN_SHELL=zsh ATUIN_QUERY=$BUFFER ATUIN_SSH_REMOTE_CONTEXT=1 ATUIN_SSH_RESULT_PROTOCOL=2 \
        "$ATUIN_LAYER_ROOT/bin/atuin-ssh-search" search -i "$@" --result-file "$result_file"
    rc=$?
    IFS= read -r -d '' output < "$result_file"
    command unlink "$result_file"
    zle reset-prompt
    print -rn -- "${zle_bracketed_paste[1]}" > /dev/tty
    if (( rc != 0 )) || [[ -z $output || $output == __atuin_insert__:$saved_buffer ]]; then
        BUFFER=$saved_buffer CURSOR=$saved_cursor MARK=$saved_mark
        zle -K "$saved_keymap"
        return $rc
    fi
    if [[ $output == __atuin_accept__:* ]]; then
        BUFFER=${output#__atuin_accept__:}
        CURSOR=${#BUFFER}
        zle accept-line
    elif [[ $output == __atuin_insert__:* ]]; then
        BUFFER=${output#__atuin_insert__:}
        CURSOR=${#BUFFER}
    fi
}

# Existing SSH functions and aliases are untouched. Explicit bypass is real
# OpenSSH, independent of whatever a user has chosen to name `ssh`.
ssh-overlay() {
    local disable_r=${ATUIN_LAYER_DISABLE_CTRL_R:-0} disable_up=${ATUIN_LAYER_DISABLE_UP:-0}
    [[ -z ${ATUIN_NOBIND+x} ]] || { disable_r=1; disable_up=1; }
    ATUIN_SSH_DISABLE_CTRL_R=$disable_r ATUIN_SSH_DISABLE_UP=$disable_up \
        command "$ATUIN_LAYER_ROOT/bin/ssh-overlay" "$@"
}
ssh-plain() { command /usr/bin/ssh "$@" }
atuin-layer() {
    if [[ $1 == history && $2 == import && " $* " == *' --local '* ]]; then
        ATUIN_LAYER_HISTFILE=${HISTFILE-} command "$ATUIN_LAYER_ROOT/bin/atuin-layer" "$@"
    else
        command "$ATUIN_LAYER_ROOT/bin/atuin-layer" "$@"
    fi
}
# New widgets need wrapping even when an existing autosuggestions plugin uses
# manual rebinding; trigger the plugin's normal lifecycle before the first ZLE.
_zsh_autosuggest_start
typeset -g ATUIN_LAYER_ACTIVE=1
