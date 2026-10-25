# Optional destination editor. The verified bundle and all its scratch files
# belong to this SSH session; native Atuin and its database remain on the hub.
# The caller supplies identity, clocks, framing and the owned temporary paths.
[[ $- == *i* && ${BASH_VERSINFO[0]} -ge 4 ]] || return 1
[[ -z ${BLE_VERSION-} && -z ${_AS_ORIGINAL_DEBUG-} && ! -o functrace ]] || return 1
[[ -r $_AS_BLE_DIR/ble.sh && -d $_AS_BLE_SESSION_DIR/runtime && -d $_AS_BLE_SESSION_DIR/cache && -d $_AS_BLE_SESSION_DIR/state ]] || return 1
(unset XDG_RUNTIME_DIR XDG_CACHE_HOME XDG_STATE_HOME 2>/dev/null) || return 1
if [[ -z ${LANG-} ]]; then (unset LANG 2>/dev/null) || return 1; fi

# Inspect GNU Readline before ble.sh imports its bindings. Explicit custom and
# unbound keys remain the user's keys, including vi-command Ctrl-R (redo).
_as_ble_original_binding() {
    local _as_map=$1 _as_key=$2 _as_function=$3 _as_row _as_found=1 _as_meta_key
    # GNU Readline prints ESC as either \e or \M- depending on convert-meta
    # and destination locale. Match both representations of the same key.
    _as_meta_key=${_as_key/\\e/\\M-}
    while IFS= read -r _as_row; do
        if [[ $_as_row == '"'"$_as_key"'": '"$_as_function" || $_as_row == '"'"$_as_meta_key"'": '"$_as_function" ]]; then
            _as_found=0
        fi
    done < <(builtin bind -m "$_as_map" -p)
    return "$_as_found"
}
_as_ble_bind_search_emacs=0 _as_ble_bind_search_vi=0 _as_ble_bind_search_normal=0
_as_ble_bind_up_emacs=0 _as_ble_bind_up_vi=0 _as_ble_bind_up_normal=0
if [[ @BIND_CTRL_R@ == 1 ]]; then
    _as_ble_original_binding emacs-standard '\C-r' reverse-search-history && _as_ble_bind_search_emacs=1
    _as_ble_original_binding vi-insert '\C-r' reverse-search-history && _as_ble_bind_search_vi=1
    _as_ble_original_binding vi-command / vi-search && _as_ble_bind_search_normal=1
fi
if [[ @BIND_UP@ == 1 ]]; then
    _as_ble_original_binding emacs-standard '\e[A' previous-history && _as_ble_bind_up_emacs=1
    _as_ble_original_binding vi-insert '\e[A' previous-history && _as_ble_bind_up_vi=1
    _as_ble_original_binding vi-command '\e[A' previous-history && _as_ble_bind_up_normal=1
fi

# Save declarations as fixed-name shell state, not as executable text. Restore
# the user's exported values before running profiles' prompt hooks/commands.
_as_ble_xdg_runtime_set=${XDG_RUNTIME_DIR+x} _as_ble_xdg_runtime=${XDG_RUNTIME_DIR-}
_as_ble_xdg_cache_set=${XDG_CACHE_HOME+x} _as_ble_xdg_cache=${XDG_CACHE_HOME-}
_as_ble_xdg_state_set=${XDG_STATE_HOME+x} _as_ble_xdg_state=${XDG_STATE_HOME-}
_as_ble_xdg_runtime_export=0 _as_ble_xdg_cache_export=0 _as_ble_xdg_state_export=0
[[ $(declare -p XDG_RUNTIME_DIR 2>/dev/null) =~ ^declare\ -[a-z]*x[a-z]*\  ]] && _as_ble_xdg_runtime_export=1
[[ $(declare -p XDG_CACHE_HOME 2>/dev/null) =~ ^declare\ -[a-z]*x[a-z]*\  ]] && _as_ble_xdg_cache_export=1
[[ $(declare -p XDG_STATE_HOME 2>/dev/null) =~ ^declare\ -[a-z]*x[a-z]*\  ]] && _as_ble_xdg_state_export=1
export XDG_RUNTIME_DIR=$_AS_BLE_SESSION_DIR/runtime
export XDG_CACHE_HOME=$_AS_BLE_SESSION_DIR/cache
export XDG_STATE_HOME=$_AS_BLE_SESSION_DIR/state
[[ -n ${LANG-} ]] || export LANG=C.UTF-8
builtin source "$_AS_BLE_DIR/ble.sh" --attach=none --norc
_as_ble_source_status=$?
if [[ $_as_ble_xdg_runtime_set ]]; then XDG_RUNTIME_DIR=$_as_ble_xdg_runtime; else unset XDG_RUNTIME_DIR; fi
if [[ $_as_ble_xdg_cache_set ]]; then XDG_CACHE_HOME=$_as_ble_xdg_cache; else unset XDG_CACHE_HOME; fi
if [[ $_as_ble_xdg_state_set ]]; then XDG_STATE_HOME=$_as_ble_xdg_state; else unset XDG_STATE_HOME; fi
[[ $_as_ble_xdg_runtime_export == 1 ]] || export -n XDG_RUNTIME_DIR
[[ $_as_ble_xdg_cache_export == 1 ]] || export -n XDG_CACHE_HOME
[[ $_as_ble_xdg_state_export == 1 ]] || export -n XDG_STATE_HOME
unset _as_ble_xdg_runtime_set _as_ble_xdg_runtime _as_ble_xdg_cache_set _as_ble_xdg_cache _as_ble_xdg_state_set _as_ble_xdg_state
unset _as_ble_xdg_runtime_export _as_ble_xdg_cache_export _as_ble_xdg_state_export
if [[ $_as_ble_source_status != 0 || ${BLE_VERSION-} != 0.4.0-nightly+d81fd54 ]]; then
    if declare -F ble/base/unload >/dev/null; then ble/base/unload; fi
    return 1
fi
unset _as_ble_source_status
# lib/_package.bash is included in the verified archive and loaded by BLE.
# Its update operation refuses downloads; the hub image owns the release.
if declare -F _as_ble_cleanup >/dev/null; then
    ble/function#copy ble/base/unload _as_ble_original_unload
    function ble/base/unload {
        _as_ble_original_unload "$@"
        local _as_status=$?
        # A reload still needs the bundle. Normal exit runs this only after
        # upstream has finalized imports, traps, runtime files and descriptors.
        if [[ $1 != reload && $_as_status == 0 && $BASH_SUBSHELL == 0 ]]; then _as_ble_cleanup; fi
        return "$_as_status"
    }
fi

_as_ble_active='' _as_ble_cmd=0 _as_ble_previous=''
_as_ble_history=$(HISTTIMEFORMAT= builtin history 1; printf '\001')
printf -v _as_ble_sentinel '\001'
_as_ble_history=${_as_ble_history%"$_as_ble_sentinel"}
_as_ble_history=${_as_ble_history%$'\n'}
if [[ $_as_ble_history =~ ^[[:space:]]*[0-9]+[[:space:]]{2}(.*)$ ]]; then
    _as_ble_previous=${BASH_REMATCH[1]}
fi
unset _as_ble_history _as_ble_sentinel
_as_ble_action=cancel _as_ble_selected=''
_as_ble_nbytes() {
    local LC_ALL=C
    _as_ble_nbytes_value=${#1}
}
_as_ble_primary() {
    [[ $_ble_attached && ! $_ble_edit_exec_inside_begin && ! $_ble_edit_read_context && ! $_ble_history_prefix ]] || return 1
    [[ $_ble_decode_keymap == emacs || $_ble_decode_keymap == vi_imap || $_ble_decode_keymap == vi_nmap ]]
}

# Compatibility shim for the pinned decoder. Upstream buffers raw input until
# the TTY is drained, then decodes it inside a function-local array. Expose only
# its untouched raw suffix through distinctly named dynamically scoped locals.
# A widget can hand that suffix to the hub before returning to the decoder.
# The one-byte path is upstream's normal <200-byte path; using it for larger
# pastes avoids hiding another chunk of user input inside the encoding decoder.
# The following modified _ble_decode_hook is derived from ble.sh:
# Copyright (c) 2013, 2015-2023, K. Murase @akinomyoga <myoga.murase@gmail.com>,
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
function _ble_decode_hook {
    builtin eval -- "$_ble_bash_POSIXLY_CORRECT_unset"
    ((_ble_decode_hook_count++))
    if ble/util/is-stdin-ready; then
        ble/array#push _ble_decode_input_buffer "$@"
        local buflen=${#_ble_decode_input_buffer[@]}
        if ((buflen%257==0&&buflen>=2000)); then
            ble-decode/.hook/adjust-volatile-options
            local IFS=$_ble_term_IFS _ble_decode_hook_Processing=prologue
            ble-decode/PROLOGUE
            _ble_decode_hook_Processing=body
            local char=${_ble_decode_input_buffer[buflen-1]}
            if ((_ble_bash<40000||char==0xC0||char==0xDE)); then
                builtin eval -- "$_ble_decode_show_progress_hook"
            else
                while ble/util/is-stdin-ready; do
                    builtin eval -- "$_ble_decode_show_progress_hook"
                    local ret; ble/decode/nonblocking-read 0.02 1 527
                    ble/array#push _ble_decode_input_buffer "${ret[@]}"
                done
            fi
            _ble_decode_hook_Processing=epilogue
            ble-decode/EPILOGUE
            ble/util/unlocal _ble_decode_hook_Processing
            local ret
            ble/array#pop _ble_decode_input_buffer
            _ble_decode_hook "$ret"
        fi
        return 0
    fi
    ble-decode/.hook/adjust-volatile-options
    local IFS=$_ble_term_IFS _ble_decode_hook_Processing=prologue
    ble-decode/PROLOGUE
    _ble_decode_hook_Processing=body
    if ble-decode/.check-abort "$1"; then
        _ble_decode_char__hook=
        _ble_decode_input_buffer=() _ble_decode_char_buffer=()
        ble/term/visible-bell "Abort by 'bleopt decode_abort_char=$bleopt_decode_abort_char'"
        shift
    fi
    local -a _as_ble_decode_bytes=("${_ble_decode_input_buffer[@]}" "$@")
    local _as_ble_decode_index _as_ble_decode_live=1
    # Do not move these bytes into ble-decode-char's own coroutine-local
    # character array before the history widget gets to hand over its suffix.
    # Pending-byte counts still suppress idle work until this batch completes.
    local ble_decode_char_sync=1
    _ble_decode_input_buffer=()
    _ble_decode_input_count=${#_as_ble_decode_bytes[@]}
    for ((_as_ble_decode_index=0;_as_ble_decode_index<${#_as_ble_decode_bytes[@]};_as_ble_decode_index++)); do
        ((--_ble_decode_input_count))
        ((_ble_debug_keylog_enabled)) && ble/array#push _ble_debug_keylog_bytes "${_as_ble_decode_bytes[_as_ble_decode_index]}"
        ble/encoding:"$bleopt_input_encoding"/decode "${_as_ble_decode_bytes[_as_ble_decode_index]}"
    done
    ble/util/unlocal ble_decode_char_sync
    ble/decode/has-input || ble-decode-key/batch/flush
    builtin eval -- "$_ble_decode_erase_progress_hook"
    _ble_decode_hook_Processing=epilogue
    ble-decode/EPILOGUE
}
_as_ble_take_buffer() {
    _as_ble_buffer_hex=''
    [[ ${_as_ble_decode_live-} == 1 ]] || return 0
    local _as_i _as_h _as_code _as_next
    for ((_as_i=_as_ble_decode_index+1;_as_i<${#_as_ble_decode_bytes[@]};_as_i++)); do
        _as_code=${_as_ble_decode_bytes[_as_i]}
        _as_next=${_as_ble_decode_bytes[_as_i+1]:--1}
        # init-bind.sh transports otherwise unbindable Readline inputs using
        # reserved UTF-8 forms. Undo those exact pinned substitutions before
        # forwarding to a different editor (including Bash 4.4's NUL macro).
        if ((_as_code==192&&(_as_next==128||_as_next==152||_as_next==155))); then
            ((_as_code=_as_next-128,_as_i++))
        elif ((_as_code==222&&(_as_next==186||_as_next==188))); then
            if ((_as_next==186)); then _as_code=79; else _as_code=27; fi
            ((_as_i++))
        fi
        printf -v _as_h '%02x' "$_as_code"
        _as_ble_buffer_hex+=$_as_h
    done
    _as_ble_decode_index=${#_as_ble_decode_bytes[@]}
    _ble_decode_input_count=0
}

# This function runs only while an actual BLE widget/idle callback owns input.
# A reply never arrives unsolicited at Bash or a foreground program. Once a
# fence was requested, only matching DONE/EOF releases input ownership.
_as_ble_rpc() {
    local _as_key=$1 _as_line=$2 _as_point=$3 _as_mark=$4 _as_map=$5
    local LC_ALL=C _as_stty _as_byte _as_h _as_pending_hex _as_fence_hex _as_fenced=0
    local _as_row _as_tail _as_data _as_value='' _as_invalid=0 _as_i _as_char
    local _as_workspace='' _as_dir=$PWD _as_ble_buffer_hex
    _as_ble_action=cancel _as_ble_selected=''
    ((${#_as_line}<=262144)) || return 1
    ((_as_req+=1))
    _as_hex "!$_AS_NONCE:$_as_req:FENCE"$'\n'; _as_fence_hex=$_as_encoded
    _as_stty=$(stty -g < /dev/tty) || return 1
    stty raw -echo < /dev/tty || return 1
    _as_ble_take_buffer
    _as_pending_hex=$_as_ble_buffer_hex
    while [[ $_as_dir == /* ]]; do
        if [[ -e $_as_dir/.git ]]; then _as_workspace=$_as_dir; break; fi
        [[ $_as_dir != / ]] || break
        _as_dir=${_as_dir%/*}; [[ $_as_dir ]] || _as_dir=/
    done
    _as_emit REQUEST "$_as_req" "$_as_key" "$_as_line" "$_as_point" "$_as_mark" "$_as_map" "$_AS_HOST" "$_AS_USER" "$PWD" "$_AS_SESSION" "$_as_workspace"
    # -d '' -n 1 distinguishes NUL (empty result) from EOF. The hex handover
    # carries every buffered byte without NUL-containing Bash variables.
    while IFS= LC_ALL=C read -r -d '' -n 1 -t 30 _as_byte < /dev/tty; do
        if [[ $_as_byte ]]; then printf -v _as_h '%02x' "'$_as_byte"; else _as_h=00; fi
        _as_pending_hex+=$_as_h
        if [[ $_as_pending_hex == *"$_as_fence_hex" ]]; then
            _as_pending_hex=${_as_pending_hex%"$_as_fence_hex"}; _as_fenced=1; break
        fi
        ((${#_as_pending_hex}<=131072)) || break
    done
    if [[ $_as_fenced == 1 ]]; then
        _as_emit HANDOVER "$_as_req" hex "$_as_pending_hex"
    else
        _as_emit ABORT "$_as_req" "$_AS_SESSION"
    fi
    while :; do
        if [[ $_as_fenced == 1 ]]; then
            IFS= read -r _as_row < /dev/tty || break
        elif IFS= read -r -t 5 _as_row < /dev/tty; then :
        else
            local _as_read_status=$?
            ((_as_read_status>128)) || break
            _as_emit ABORT "$_as_req" "$_AS_SESSION"; continue
        fi
        [[ $_as_row == "!$_AS_NONCE:$_as_req:"* ]] || continue
        _as_tail=${_as_row#"!$_AS_NONCE:$_as_req:"}
        case $_as_tail in
            DATA:*)
                _as_data=${_as_tail#DATA:}
                if [[ $_as_data == *[!0123456789abcdef]* ]] || ((${#_as_data}%2||${#_as_value}+${#_as_data}>524288)); then
                    _as_invalid=1
                elif [[ $_as_invalid == 0 ]]; then _as_value+=$_as_data; fi ;;
            DONE:insert|DONE:accept|DONE:cancel) _as_ble_action=${_as_tail#DONE:}; break ;;
        esac
    done
    [[ $_as_invalid == 0 ]] || _as_ble_action=cancel
    if [[ $_as_ble_action != cancel ]]; then
        for ((_as_i=0;_as_i<${#_as_value};_as_i+=2)); do
            if [[ ${_as_value:_as_i:2} == 00 ]]; then _as_ble_action=cancel; break; fi
            printf -v _as_char '%b' "\x${_as_value:_as_i:2}"
            _as_ble_selected+=$_as_char
        done
    fi
    stty "$_as_stty" < /dev/tty
    _as_emit RELEASE "$_as_req" "$_AS_SESSION"
    [[ $_as_ble_action != cancel ]]
}

_as_ble_widget() {
    local _as_key=$1 _as_map _as_point _as_mark _as_prefix
    if ! _as_ble_primary; then
        if [[ $_as_key == up ]]; then ble/widget/backward-line
        else ble/widget/history-isearch-backward; fi
        return "$?"
    fi
    if [[ $_as_key == up && ${_ble_edit_str::_ble_edit_ind} == *$'\n'* ]]; then
        ble/widget/backward-line
        return "$?"
    fi
    # Cancel only the unaccepted ghost. Its visible suffix is not user input.
    [[ $_ble_edit_mark_active != auto_complete ]] || ble/widget/auto_complete/cancel
    case $_ble_decode_keymap in
        emacs) _as_map=emacs-standard ;;
        vi_imap) _as_map=vi-insert ;;
        vi_nmap) _as_map=vi-command ;;
    esac
    _as_prefix=${_ble_edit_str::_ble_edit_ind}; _as_ble_nbytes "$_as_prefix"; _as_point=$_as_ble_nbytes_value
    _as_prefix=${_ble_edit_str::_ble_edit_mark}; _as_ble_nbytes "$_as_prefix"; _as_mark=$_as_ble_nbytes_value
    ble/edit/enter-command-layout
    ble/widget/.hide-current-line keep-header
    ble/term/leave-for-widget
    ble/util/buffer.flush
    _as_ble_rpc "$_as_key" "$_ble_edit_str" "$_as_point" "$_as_mark" "$_as_map" || :
    ble/term/enter-for-widget
    ble/edit/leave-command-layout
    # The widget uses a nested C locale only to convert offsets. Selection is
    # decoded as bytes by RPC, then BLE counts characters in the shell locale.
    if [[ $_as_ble_action == insert || $_as_ble_action == accept ]]; then
        ble-edit/content/reset "$_as_ble_selected"
        _ble_edit_ind=${#_ble_edit_str} _ble_edit_mark=0 _ble_edit_mark_active=
        [[ $_as_ble_action != accept ]] || ble/widget/accept-line
    fi
    ble/textarea#invalidate
    return 0
}
function ble/widget/atuin-ssh/search { _as_ble_widget search; }
function ble/widget/atuin-ssh/up { _as_ble_widget up; }

function ble/complete/auto-complete/source:atuin-ssh {
    _as_ble_primary || return 1
    ((_ble_edit_ind==${#_ble_edit_str})) || return 1
    [[ $_ble_edit_str && $_ble_edit_str != ' '* ]] || return 1
    ble/decode/has-input && return 148
    local _as_snapshot=$_ble_edit_str _as_index=$_ble_edit_ind
    local _as_bytes _as_map=emacs-standard
    case $_ble_decode_keymap in vi_imap) _as_map=vi-insert ;; vi_nmap) _as_map=vi-command ;; esac
    _as_ble_nbytes "$_as_snapshot"; _as_bytes=$_as_ble_nbytes_value
    ((_as_bytes<=4096)) || return 1
    _as_ble_rpc suggest "$_as_snapshot" "$_as_bytes" "$_as_bytes" "$_as_map" || return 1
    [[ $_as_ble_action == insert && $_ble_edit_str == "$_as_snapshot" && $_ble_edit_ind == "$_as_index" ]] || return 1
    # Never render a reply over a newly queued edit. The relay cancels and
    # replays pre-fence typeahead; BLE will process it normally after RELEASE.
    ble/decode/has-input && return 148
    [[ $_as_ble_selected == "$_as_snapshot"?* ]] || return 1
    [[ $_as_ble_selected != *[$'\001'-$'\037'$'\177']* ]] || return 1
    ble/complete/auto-complete/enter h 0 "${_as_ble_selected:${#_as_snapshot}}" '' "$_as_ble_selected"
}
_as_ble_complete_setup() {
    # No local-history/syntax fallback: automatic history comes only from the
    # hub's native Atuin with its verified destination/account context.
    _ble_complete_auto_source=(atuin-ssh)
    bleopt complete_auto_complete=1 complete_auto_delay=200 complete_auto_menu=0
}
blehook/eval-after-load complete _as_ble_complete_setup

_as_ble_preexec() {
    local _as_status=$? _as_text=$1 _as_pattern _as_patterns=${HISTIGNORE-}
    [[ $BASH_SUBSHELL == 0 && ! $_ble_edit_read_context && ! $_ble_history_prefix ]] || return "$_as_status"
    _as_ble_active=''
    [[ -o history && $_as_text && $_as_text != ' '* ]] || return "$_as_status"
    if [[ $_as_text == $'\t'* && ( :${HISTCONTROL-}: == *:ignorespace:* || :${HISTCONTROL-}: == *:ignoreboth:* ) ]]; then
        return "$_as_status"
    fi
    local LC_ALL=C
    if ((${#_as_text}>262144)); then
        _as_emit DEGRADED 'Accepted command exceeds capture bound.'; return "$_as_status"
    fi
    # Preserve explicit history exclusions. Complex escaped delimiters and &
    # expansions fail closed rather than inventing a different Bash policy.
    while [[ $_as_patterns ]]; do
        _as_pattern=${_as_patterns%%:*}
        if [[ $_as_pattern == '&' ]]; then
            [[ $_as_text != "$_as_ble_previous" ]] || return "$_as_status"
        elif [[ $_as_pattern == *'\'* || $_as_pattern == *'&'* ]]; then
            _as_emit DEGRADED 'Complex HISTIGNORE: repeated-command capture unavailable; native history exclusions preserved.'
            return "$_as_status"
        else
            case $_as_text in $_as_pattern) return "$_as_status" ;; esac
        fi
        [[ $_as_patterns == *:* ]] || break
        _as_patterns=${_as_patterns#*:}
    done
    _as_ble_previous=$_as_text
    if _as_clock; then
        ((_as_ble_cmd+=1)); _as_ble_active=$_AS_SESSION:$_as_ble_cmd
        _as_emit START "$_as_ble_active" "$_as_text" "$_AS_HOST" "$_AS_USER" "$PWD" "$_AS_SESSION" "$_as_timestamp"
    else
        _as_emit DEGRADED 'Wall clock failed: capture and native hub keys disabled for this shell.'
    fi
    return "$_as_status"
}
_as_ble_postexec() {
    local _as_status=$?
    [[ $BASH_SUBSHELL == 0 && ! $_ble_edit_read_context && ! $_ble_history_prefix ]] || return "$_as_status"
    if [[ $_as_ble_active ]]; then
        if _as_clock; then _as_emit END "$_as_ble_active" "$_as_status" "$_as_timestamp"
        else _as_emit DEGRADED 'Wall clock failed: completion remains pending; capture and native hub keys disabled for this shell.'; fi
        _as_ble_active=''
    fi
    return "$_as_status"
}
_as_ble_prompt() {
    local _as_status=$?
    [[ $BASH_SUBSHELL == 0 && ! $_ble_edit_read_context && ! $_ble_history_prefix && ! $_ble_edit_exec_inside_begin ]] || return "$_as_status"
    _as_emit PROMPT "$PWD"
    return "$_as_status"
}
# A PRECMD hook's mere presence makes this pinned BLE version reevaluate PS1
# inside its foreground read -e editor, replacing read's own -p prompt. The
# end-of-command-batch hook is the same visibility boundary without introducing
# a primary-prompt hook into that nested editor.
blehook PREEXEC+=_as_ble_preexec POSTEXEC+=_as_ble_postexec exec_end+=_as_ble_prompt

# Loading each map now allows normal inputrc import to complete before these
# optional replacements. The native vi-command Ctrl-R redo remains untouched.
ble/decode/keymap#load emacs
ble/decode/keymap#load vi_imap
ble/decode/keymap#load vi_nmap
[[ $_as_ble_bind_search_emacs != 1 ]] || ble-bind -m emacs -f C-r atuin-ssh/search
[[ $_as_ble_bind_search_vi != 1 ]] || ble-bind -m vi_imap -f C-r atuin-ssh/search
[[ $_as_ble_bind_search_normal != 1 ]] || ble-bind -m vi_nmap -f / atuin-ssh/search
[[ $_as_ble_bind_up_emacs != 1 ]] || ble-bind -m emacs -f up atuin-ssh/up
[[ $_as_ble_bind_up_vi != 1 ]] || ble-bind -m vi_imap -f up atuin-ssh/up
[[ $_as_ble_bind_up_normal != 1 ]] || ble-bind -m vi_nmap -f up atuin-ssh/up
_as_ble_hello() {
    [[ ${_as_ble_announced-} != 1 ]] || return 0
    _as_ble_announced=1
    _as_emit HELLO "$_AS_HOST" "$_AS_USER" "$PWD" "$_AS_SESSION" bash
    _as_ble_prompt
}
blehook ATTACH+=_as_ble_hello
if ! ble-attach; then
    ble/base/unload
    return 1
fi
