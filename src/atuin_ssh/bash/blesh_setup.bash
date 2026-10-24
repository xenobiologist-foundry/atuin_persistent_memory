# Session-only editor bundle transfer. Source after the user's login profiles.
_AS_BLE_SETUP_NONCE='@NONCE@'
_AS_BLE_SETUP_SESSION='@SESSION@'
_AS_BLE_EXPECTED_SIZE='@BUNDLE_SIZE@'
_AS_BLE_EXPECTED_SHA='@BUNDLE_SHA256@'
_as_bundle_seq=0
_as_boot_seq=0
_AS_BLE_DIR=''
_AS_BLE_SESSION_DIR=''
_AS_BLE_SAVED_STTY=''

_as_ble_restore_tty() {
    if [[ -n ${_AS_BLE_SAVED_STTY-} ]]; then
        command stty "$_AS_BLE_SAVED_STTY" < /dev/tty 2>/dev/null || :
        _AS_BLE_SAVED_STTY=''
    fi
}
_as_ble_cleanup() {
    _as_ble_restore_tty
    local _as_ble_leaf=${_AS_BLE_SESSION_DIR##*/}
    if [[ -n ${_AS_BLE_TEMP_PARENT-} && -n ${_AS_BLE_SESSION_DIR-}
          && ${_AS_BLE_SESSION_DIR%/*} == "$_AS_BLE_TEMP_PARENT"
          && $_as_ble_leaf == atuin-ssh-blesh.*
          && ${_as_ble_leaf#atuin-ssh-blesh.} =~ ^[A-Za-z0-9]{8}$
          && -d $_AS_BLE_SESSION_DIR && ! -L $_AS_BLE_SESSION_DIR
          && -O $_AS_BLE_SESSION_DIR ]]; then
        command rm -rf -- "$_AS_BLE_SESSION_DIR"
    fi
    _AS_BLE_DIR='' _AS_BLE_SESSION_DIR=''
}
_as_ble_hex() {
    local LC_ALL=C _as_ble_text=$1 _as_ble_i _as_ble_n _as_ble_h
    _as_ble_encoded=''
    for ((_as_ble_i=0; _as_ble_i<${#_as_ble_text}; _as_ble_i++)); do
        printf -v _as_ble_n '%d' "'${_as_ble_text:_as_ble_i:1}"
        printf -v _as_ble_h '%02x' "$_as_ble_n"
        _as_ble_encoded+=$_as_ble_h
    done
}
_as_bundle_emit() {
    local _as_ble_kind=$1 _as_ble_field _as_ble_encoded _as_ble_frame
    shift
    ((_as_bundle_seq+=1))
    _as_boot_seq=$_as_bundle_seq
    _as_ble_frame=$'\e]777;atuin-ssh;1;'"$_AS_BLE_SETUP_NONCE;$_as_bundle_seq;$_as_ble_kind"
    for _as_ble_field in "$@"; do
        _as_ble_hex "$_as_ble_field"
        _as_ble_frame+=";$_as_ble_encoded"
    done
    printf '%s\a' "$_as_ble_frame" > /dev/tty
}
_as_ble_abort_wait() {
    # A timeout is not permission to hand late DATA to Readline. Ownership
    # returns only after the relay's ordered abort END or actual tty EOF.
    local _as_ble_row _as_ble_read_status
    local _as_ble_abort="!$_AS_BLE_SETUP_NONCE:BUNDLE:END:0:0000000000000000000000000000000000000000000000000000000000000000"
    _as_bundle_emit BUNDLE_ABORT "$_AS_BLE_SETUP_SESSION" || return 1
    while :; do
        if IFS= read -r -t 10 _as_ble_row < /dev/tty; then
            ((${#_as_ble_row} <= 8192)) || continue
            [[ $_as_ble_row != "$_as_ble_abort" ]] || return 1
        else
            _as_ble_read_status=$?
            ((_as_ble_read_status > 128)) || return 1
            _as_bundle_emit BUNDLE_ABORT "$_AS_BLE_SETUP_SESSION" || return 1
        fi
    done
}
_as_ble_wait_fence() {
    local LC_ALL=C _as_ble_byte _as_ble_h _as_ble_n _as_ble_pending=''
    local _as_ble_fence=$'!'"$_AS_BLE_SETUP_NONCE:BUNDLE:FENCE"$'\n' _as_ble_fence_hex
    _as_ble_hex "$_as_ble_fence"
    _as_ble_fence_hex=$_as_ble_encoded
    # With a NUL delimiter an empty successful read denotes a literal NUL.
    # Keep pending input as hex because Bash strings cannot contain NUL.
    while IFS= LC_ALL=C read -r -d '' -n 1 -t 30 _as_ble_byte < /dev/tty; do
        if [[ -n $_as_ble_byte ]]; then
            printf -v _as_ble_n '%d' "'$_as_ble_byte"
            printf -v _as_ble_h '%02x' "$_as_ble_n"
        else
            _as_ble_h=00
        fi
        _as_ble_pending+=$_as_ble_h
        if [[ $_as_ble_pending == *"$_as_ble_fence_hex" ]]; then
            _as_ble_pending=${_as_ble_pending%"$_as_ble_fence_hex"}
            _as_bundle_emit BUNDLE_HANDOVER "$_AS_BLE_SETUP_SESSION" "$_as_ble_pending"
            return $?
        fi
        ((${#_as_ble_pending} <= 131072 + ${#_as_ble_fence_hex})) || break
    done
    _as_ble_abort_wait
}
_as_ble_hash_file() {
    local _as_ble_digest
    case $_AS_BLE_HASH_TOOL in
        sha256sum) _as_ble_digest=$(command sha256sum "$1") || return 1
                   _as_ble_digest=${_as_ble_digest%% *} ;;
        shasum) _as_ble_digest=$(command shasum -a 256 "$1") || return 1
                _as_ble_digest=${_as_ble_digest%% *} ;;
        openssl) _as_ble_digest=$(command openssl dgst -sha256 "$1") || return 1
                 _as_ble_digest=${_as_ble_digest##* } ;;
        *) return 1 ;;
    esac
    [[ $_as_ble_digest =~ ^[a-f0-9]{64}$ ]] || return 1
    [[ $_as_ble_digest == "$_AS_BLE_EXPECTED_SHA" ]]
}
_as_ble_receive() {
    local LC_ALL=C _as_ble_tool _as_ble_parent _as_ble_leaf _as_ble_row _as_ble_chunk
    local _as_ble_bad=0 _as_ble_count=0 _as_ble_limit _as_ble_status _as_ble_bytes
    [[ $_AS_BLE_SETUP_NONCE =~ ^[a-f0-9]{32}$
       && $_AS_BLE_SETUP_SESSION =~ ^[a-f0-9]{32}$
       && $_AS_BLE_EXPECTED_SIZE =~ ^[1-9][0-9]{0,7}$
       && $_AS_BLE_EXPECTED_SHA =~ ^[a-f0-9]{64}$ ]] || return 1
    ((_AS_BLE_EXPECTED_SIZE <= 8388608)) || return 1
    for _as_ble_tool in mktemp chmod mkdir rm tar base64 wc stty; do
        command -v "$_as_ble_tool" > /dev/null 2>&1 || return 1
    done
    if command -v sha256sum > /dev/null 2>&1; then _AS_BLE_HASH_TOOL=sha256sum
    elif command -v shasum > /dev/null 2>&1; then _AS_BLE_HASH_TOOL=shasum
    elif command -v openssl > /dev/null 2>&1; then _AS_BLE_HASH_TOOL=openssl
    else return 1
    fi
    [[ $(printf YQ== | command base64 -d 2>/dev/null) == a ]] || return 1
    _as_ble_parent=${TMPDIR:-/tmp}
    [[ $_as_ble_parent == /* && -d $_as_ble_parent ]] || return 1
    _as_ble_parent=$(builtin cd -- "$_as_ble_parent" && builtin pwd -P) || return 1
    _AS_BLE_TEMP_PARENT=$_as_ble_parent
    _AS_BLE_SESSION_DIR=$(umask 077; command mktemp -d "$_as_ble_parent/atuin-ssh-blesh.XXXXXXXX") || return 1
    _as_ble_leaf=${_AS_BLE_SESSION_DIR##*/}
    [[ ${_AS_BLE_SESSION_DIR%/*} == "$_AS_BLE_TEMP_PARENT"
       && $_as_ble_leaf == atuin-ssh-blesh.*
       && ${_as_ble_leaf#atuin-ssh-blesh.} =~ ^[A-Za-z0-9]{8}$
       && -O $_AS_BLE_SESSION_DIR && ! -L $_AS_BLE_SESSION_DIR ]] || return 1
    command chmod 0700 "$_AS_BLE_SESSION_DIR" || return 1
    command mkdir -m 0700 "$_AS_BLE_SESSION_DIR/tree" "$_AS_BLE_SESSION_DIR/runtime" \
        "$_AS_BLE_SESSION_DIR/cache" "$_AS_BLE_SESSION_DIR/state" || return 1
    (umask 077; : > "$_AS_BLE_SESSION_DIR/bundle.b64") || return 1
    _AS_BLE_SAVED_STTY=$(command stty -g < /dev/tty) || return 1
    command stty raw -echo < /dev/tty || return 1
    _as_bundle_emit BUNDLE_REQUEST "$_AS_BLE_SETUP_SESSION" || return 1
    _as_ble_wait_fence || return 1
    _as_ble_limit=$(( ((_AS_BLE_EXPECTED_SIZE+2)/3)*4 ))
    while :; do
        if IFS= read -r -t 30 _as_ble_row < /dev/tty; then
            # The hub's verified iterator bounds each line to 4143 bytes and
            # holds workstation input. Avoid read -n, which forces a syscall
            # for every byte on Bash's raw tty and slows the whole bundle.
            if ((${#_as_ble_row}>8192)); then _as_ble_bad=1; continue; fi
            case $_as_ble_row in
                "!$_AS_BLE_SETUP_NONCE:BUNDLE:DATA:"*)
                    _as_ble_chunk=${_as_ble_row#"!$_AS_BLE_SETUP_NONCE:BUNDLE:DATA:"}
                    if [[ -z $_as_ble_chunk || $_as_ble_chunk == *[!A-Za-z0-9+/=]* ]] \
                            || ((${#_as_ble_chunk}>4096)); then
                        _as_ble_bad=1
                    fi
                    ((_as_ble_count+=${#_as_ble_chunk}))
                    ((_as_ble_count <= _as_ble_limit)) || _as_ble_bad=1
                    if [[ $_as_ble_bad == 0 ]]; then
                        printf '%s\n' "$_as_ble_chunk" >> "$_AS_BLE_SESSION_DIR/bundle.b64" || _as_ble_bad=1
                    fi ;;
                "!$_AS_BLE_SETUP_NONCE:BUNDLE:END:"*)
                    [[ $_as_ble_row == "!$_AS_BLE_SETUP_NONCE:BUNDLE:END:$_AS_BLE_EXPECTED_SIZE:$_AS_BLE_EXPECTED_SHA" ]] || _as_ble_bad=1
                    break ;;
                *) _as_ble_bad=1 ;;
            esac
        else
            _as_ble_status=$?
            if ((_as_ble_status > 128)); then _as_ble_abort_wait; fi
            return 1
        fi
    done
    [[ $_as_ble_bad == 0 && $_as_ble_count == "$_as_ble_limit" ]] || return 1
    if ! (umask 077; command base64 -d < "$_AS_BLE_SESSION_DIR/bundle.b64" \
            > "$_AS_BLE_SESSION_DIR/bundle.tar" 2>/dev/null); then return 1; fi
    _as_ble_bytes=$(command wc -c < "$_AS_BLE_SESSION_DIR/bundle.tar") || return 1
    _as_ble_bytes=${_as_ble_bytes//[[:space:]]/}
    [[ $_as_ble_bytes == "$_AS_BLE_EXPECTED_SIZE" ]] || return 1
    _as_ble_hash_file "$_AS_BLE_SESSION_DIR/bundle.tar" || return 1
    command tar -xf "$_AS_BLE_SESSION_DIR/bundle.tar" -C "$_AS_BLE_SESSION_DIR/tree" || return 1
    [[ -r $_AS_BLE_SESSION_DIR/tree/ble.sh && -r $_AS_BLE_SESSION_DIR/tree/lib/_package.bash ]] || return 1
    command rm -f -- "$_AS_BLE_SESSION_DIR/bundle.b64" "$_AS_BLE_SESSION_DIR/bundle.tar"
    _AS_BLE_DIR=$_AS_BLE_SESSION_DIR/tree
    return 0
}
if _as_ble_receive; then
    _as_ble_restore_tty
else
    _as_ble_cleanup
    printf '%s\n' 'atuin-ssh: temporary inline editor unavailable; continuing with ordinary Bash integration.' >&2
fi
