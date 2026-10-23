# This file is delivered in memory. No destination files are created.
[[ $- == *i* && ${BASH_VERSINFO[0]} -ge 5 ]] || return
[[ -z ${_AS_NONCE-} ]] || return
if ! (unset PROMPT_COMMAND 2>/dev/null); then return; fi
_AS_NONCE='@NONCE@'
_AS_SESSION='@SESSION@'
_as_user_prompt='\u'
_AS_USER=${_as_user_prompt@P}
_AS_HOST=$HOSTNAME
unset _as_user_prompt
_as_seq=0 _as_req=0 _as_cmd=0 _as_ready=0 _as_active='' _as_last_status=0
_as_history_number=''
_as_initial_history=$(HISTTIMEFORMAT= builtin history 1)
if [[ $_as_initial_history =~ ^[[:space:]]*([0-9]+)[[:space:]] ]]; then
    _as_history_number=${BASH_REMATCH[1]}
fi
unset _as_initial_history

_as_hex() {
    local LC_ALL=C _as_s=$1 _as_i _as_n _as_h
    _as_encoded=''
    for ((_as_i=0; _as_i<${#_as_s}; _as_i++)); do
        printf -v _as_n '%d' "'${_as_s:_as_i:1}"
        printf -v _as_h '%02x' "$_as_n"
        _as_encoded+=$_as_h
    done
}
_as_emit() {
    local _as_kind=$1 _as_field _as_encoded _as_frame
    shift
    ((_as_seq+=1))
    _as_frame=$'\e]777;atuin-ssh;1;'"$_AS_NONCE;$_as_seq;$_as_kind"
    for _as_field in "$@"; do
        _as_hex "$_as_field"
        _as_frame+=";$_as_encoded"
    done
    printf '%s\a' "$_as_frame" > /dev/tty
}
_as_widget() {
    local LC_ALL=C
    local _as_key=$1 _as_map=$2 _as_stty _as_byte _as_pending='' _as_fence _as_row
    local _as_value='' _as_action=cancel _as_data _as_tail _as_char _as_i _as_invalid=0 _as_fenced=0 _as_workspace='' _as_dir=$PWD
    bind -m "$_as_map" '"\C-x\C-_H0\a": ""'
    ((_as_req+=1))
    _as_fence="!$_AS_NONCE:$_as_req:FENCE"$'\n'
    _as_stty=$(stty -g < /dev/tty) || return
    stty raw -echo < /dev/tty
    while [[ $_as_dir == /* ]]; do
        if [[ -e $_as_dir/.git ]]; then _as_workspace=$_as_dir; break; fi
        [[ $_as_dir != / ]] || break
        _as_dir=${_as_dir%/*}
        [[ -n $_as_dir ]] || _as_dir=/
    done
    _as_emit REQUEST "$_as_req" "$_as_key" "$READLINE_LINE" "$READLINE_POINT" "${READLINE_MARK:-0}" "$_as_map" "$_AS_HOST" "$_AS_USER" "$PWD" "$_AS_SESSION" "$_as_workspace"
    # Bytes already sent before REQUEST are owned by the widget. The fence is
    # sent on the same ordered SSH input stream, after the hub stops forwarding.
    while IFS= LC_ALL=C read -r -N 1 -t 30 _as_byte < /dev/tty; do
        _as_pending+=$_as_byte
        if [[ $_as_pending == *"$_as_fence" ]]; then
            _as_pending=${_as_pending%"$_as_fence"}
            _as_fenced=1
            break
        fi
        if ((${#_as_pending}>65536)); then break; fi
    done
    if [[ $_as_fenced == 1 ]]; then
        _as_emit HANDOVER "$_as_req" "$_as_pending"
    else
        # Keep tty ownership until the relay acknowledges cancellation. Never
        # return to a shell that could receive a delayed protocol response.
        _as_emit ABORT "$_as_req" "$_AS_SESSION"
    fi
    # Do not return to Readline on an idle UI timer: a late result could then
    # become shell input. Ownership ends only with a matching DONE or tty EOF.
    while :; do
        if [[ $_as_fenced == 1 ]]; then
            IFS= read -r _as_row < /dev/tty || break
        elif IFS= read -r -t 5 _as_row < /dev/tty; then
            :
        else
            local _as_read_status=$?
            ((_as_read_status > 128)) || break
            _as_emit ABORT "$_as_req" "$_AS_SESSION"
            continue
        fi
        [[ $_as_row == "!$_AS_NONCE:$_as_req:"* ]] || continue
        _as_tail=${_as_row#"!$_AS_NONCE:$_as_req:"}
        case $_as_tail in
            DATA:*)
                _as_data=${_as_tail#DATA:}
                if [[ $_as_data == *[!0123456789abcdef]* ]] || ((${#_as_data}%2 || ${#_as_value}+${#_as_data}>1048576)); then
                    _as_invalid=1
                elif [[ $_as_invalid == 0 ]]; then
                    _as_value+=$_as_data
                fi ;;
            DONE:insert|DONE:accept|DONE:cancel)
                _as_action=${_as_tail#DONE:}; break ;;
        esac
    done
    [[ $_as_invalid == 0 ]] || _as_action=cancel
    stty "$_as_stty" < /dev/tty
    _as_emit RELEASE "$_as_req" "$_AS_SESSION"
    if [[ $_as_action == insert || $_as_action == accept ]]; then
        local LC_ALL=C _as_selected=''
        for ((_as_i=0;_as_i<${#_as_value};_as_i+=2)); do
            [[ ${_as_value:_as_i:2} != 00 ]] || return
            printf -v _as_char '%b' "\x${_as_value:_as_i:2}"
            _as_selected+=$_as_char
        done
        READLINE_LINE=$_as_selected
        READLINE_POINT=${#READLINE_LINE}
        if [[ $_as_action == accept ]]; then
            bind -m "$_as_map" '"\C-x\C-_H0\a": accept-line'
        fi
    fi
}
_as_bind() {
    local _as_map=$1 _as_key=$2 _as_mode=$3
    # Two-step native Atuin macro semantics. No command text is evaluated.
    bind -m "$_as_map" -x '"\C-x\C-_H1\a": _as_widget '"$_as_mode $_as_map"
    bind -m "$_as_map" '"\C-x\C-_H0\a": ""'
    bind -m "$_as_map" '"'"$_as_key"'": "\C-x\C-_H1\a\C-x\C-_H0\a"'
}
_as_default_binding() {
    # Respect explicit inputrc/custom bindings, including an unbound key. Only
    # replace ordinary Readline history functions with this integration.
    local _as_map=$1 _as_key=$2 _as_binding
    while IFS= read -r _as_binding; do
        case $_as_binding in
            '"'"$_as_key"'": reverse-search-history'|'"'"$_as_key"'": previous-history'|'"'"$_as_key"'": history-search-backward'|'"'"$_as_key"'": non-incremental-reverse-search-history'|'"'"$_as_key"'": vi-search') return 0 ;;
        esac
    done < <(bind -m "$_as_map" -p)
    return 1
}
if [[ @BIND_CTRL_R@ == 1 ]]; then
    for _as_map in emacs-standard vi-insert; do
        _as_default_binding "$_as_map" '\C-r' && _as_bind "$_as_map" '\C-r' search
    done
    _as_default_binding vi-command '/' && _as_bind vi-command '/' search
fi
# Separate callback slots preserve Up's native --shell-up-key-binding option.
_as_up() { _as_widget up "$1"; }
for _as_map in emacs-standard vi-insert vi-command; do
    [[ @BIND_UP@ == 1 ]] || break
    bind -m "$_as_map" -x '"\C-x\C-_H2\a": _as_up '"$_as_map"
    _as_default_binding "$_as_map" '\e[A' && bind -m "$_as_map" '"\e[A": "\C-x\C-_H2\a\C-x\C-_H0\a"'
    _as_default_binding "$_as_map" '\eOA' && bind -m "$_as_map" '"\eOA": "\C-x\C-_H2\a\C-x\C-_H0\a"'
done
unset _as_map

_as_debug() {
    [[ $_as_ready == 1 ]] || return 0
    [[ -z ${READLINE_LINE+x} && -z ${COMP_LINE+x} && $BASH_SUBSHELL == 0 ]] || return 0
    _as_ready=0
    _as_active=''
    local LC_ALL=C _as_history _as_text _as_number
    [[ -o history ]] || return 0
    _as_history=$(HISTTIMEFORMAT= builtin history 1; printf '\001')
    _as_history=${_as_history%$'\001'}
    _as_history=${_as_history%$'\n'}
    if [[ $_as_history =~ ^[[:space:]]*([0-9]+)[[:space:]]+(.*)$ ]]; then
        _as_number=${BASH_REMATCH[1]}
        _as_text=${BASH_REMATCH[2]}
        [[ $_as_number != "$_as_history_number" ]] || return 0
        _as_history_number=$_as_number
        [[ -n $_as_text ]] || return 0
        if ((${#_as_text}>262144)); then
            _as_emit DEGRADED 'Accepted command exceeds capture bound.'
            return 0
        fi
        ((_as_cmd+=1))
        _as_active=$_AS_SESSION:$_as_cmd
        _as_emit START "$_AS_SESSION:$_as_cmd" "$_as_text" "$_AS_HOST" "$_AS_USER" "$PWD" "$_AS_SESSION" "$EPOCHREALTIME"
    fi
    return 0
}
_as_prompt() {
    local _as_status=$?
    _as_last_status=$_as_status
    _as_ready=0
    if [[ -n $_as_active ]]; then
        _as_emit END "$_as_active" "$_as_status" "$EPOCHREALTIME"
        _as_active=''
    fi
    _as_emit PROMPT "$PWD"
    return "$_as_status"
}
_as_arm() { _as_ready=1; return "$_as_last_status"; }
# Leave existing traps intact. Key integration remains usable if capture cannot
# safely compose with a pre-existing preexec framework.
if [[ -z $(trap -p DEBUG) && ! -o functrace ]]; then
    trap '_as_debug' DEBUG
else
    _as_emit DEGRADED 'Existing DEBUG trap/functrace: capture unavailable; keys remain enabled.'
fi
if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == 'declare -a '* ]]; then
    PROMPT_COMMAND=(_as_prompt "${PROMPT_COMMAND[@]}" _as_arm)
else
    PROMPT_COMMAND=(_as_prompt "${PROMPT_COMMAND-}" _as_arm)
fi
_as_emit HELLO "$_AS_HOST" "$_AS_USER" "$PWD" "$_AS_SESSION" bash
