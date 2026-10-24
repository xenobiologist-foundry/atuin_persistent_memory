"""In-memory Bash bootstrap. Never send the payload as interactive keystrokes."""
from importlib.resources import files
import os
import shlex


def remote_command(nonce: str, session: str, *, force_bash: bool = False, bundle=None) -> str:
    payload = files("atuin_ssh").joinpath("bash/remote.bash").read_text()
    payload = payload.replace("@NONCE@", nonce).replace("@SESSION@", session)
    payload = payload.replace("@MIN_BASH_MAJOR@", "4" if force_bash else "5")
    payload = payload.replace("@BIND_CTRL_R@", "0" if os.environ.get("ATUIN_SSH_DISABLE_CTRL_R") == "1" else "1")
    payload = payload.replace("@BIND_UP@", "0" if os.environ.get("ATUIN_SSH_DISABLE_UP") == "1" else "1")
    editor_payload = payload
    if bundle is not None:
        setup = files("atuin_ssh").joinpath("bash/blesh_setup.bash").read_text()
        setup = (setup.replace("@NONCE@", nonce).replace("@SESSION@", session)
                 .replace("@BUNDLE_SIZE@", str(bundle.size)).replace("@BUNDLE_SHA256@", bundle.sha256))
        adapter = files("atuin_ssh").joinpath("bash/remote_ble.bash").read_text()
        adapter = adapter.replace("@BIND_CTRL_R@", "0" if os.environ.get("ATUIN_SSH_DISABLE_CTRL_R") == "1" else "1")
        adapter = adapter.replace("@BIND_UP@", "0" if os.environ.get("ATUIN_SSH_DISABLE_UP") == "1" else "1")
        # Reuse only the representation/clock/framing primitives. GNU
        # Readline bindings and DEBUG lifecycle hooks are replaced by the
        # destination BLE adapter in this explicitly selected editor mode.
        common = payload[:payload.index("_as_accept_snapshot()")]
        editor_payload = r'''_as_ble_prompt_compatible() {
    local _as_prompt_hook
    for _as_prompt_hook in "${PROMPT_COMMAND[@]-}"; do
        [[ $_as_prompt_hook != *[!$' \t\n']* ]] || return 1
    done
}
_as_editor_prompt_ok=1
if ! _as_ble_prompt_compatible; then
    _as_editor_prompt_ok=0
    printf '%s\n' 'atuin-ssh: custom prompt hooks use destination GNU Readline; inline suggestions are unavailable for this session.' >&2
fi
unset -f _as_ble_prompt_compatible
if [[ $_as_editor_prompt_ok == 1 && -z ${_AS_ORIGINAL_DEBUG-} && ! -o functrace && -z ${_AS_NONCE-} ]] &&
   ! declare -F ble-attach >/dev/null && (unset PROMPT_COMMAND 2>/dev/null); then
''' + setup + r'''
fi
if [[ -n ${_AS_BLE_DIR-} ]]; then
    exec {_as_ble_adapter_fd}<<'__ATUIN_SSH_BLE_EDITOR__'
''' + common + adapter + r'''
__ATUIN_SSH_BLE_EDITOR__
    if ! builtin source /dev/fd/$_as_ble_adapter_fd; then
        _as_boot_seq=${_as_seq:-${_as_boot_seq:-0}}
        unset _AS_NONCE _AS_SESSION
        declare -F _as_ble_cleanup >/dev/null && _as_ble_cleanup
''' + payload + r'''
    fi
    exec {_as_ble_adapter_fd}<&-
    unset _as_ble_adapter_fd
else
''' + payload + r'''
fi
'''
    unsupported_version = ("BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4)"
                           if force_bash else "BASH_VERSINFO[0] < 5")
    version_notice = ("atuin-ssh: Bash 4.4 or newer is required for requested native history integration; continuing with an ordinary Bash login shell"
                      if force_bash else
                      "atuin-ssh: Bash 5 or newer is required for native history integration; continuing with an ordinary Bash login shell")
    # Bash 4.4 has no EPOCHREALTIME. Verify a usable native date component
    # before exporting the hook, so an unsupported clock stays an ordinary
    # login session instead of installing capture with fabricated timestamps.
    clock_preflight = r'''if (( BASH_VERSINFO[0] == 4 )); then
    if ! _as_clock_probe=$(command date '+%s %N' 2>/dev/null) || [[ ! $_as_clock_probe =~ ^([0-9]{1,12})\ ([0-9]{1,9})$ ]]; then
        printf '%s\n' 'atuin-ssh: Bash 4.4 clock support is unavailable; continuing with an ordinary Bash login shell' >&2
        exec bash --login -i
    fi
    unset _as_clock_probe
fi
'''
    launcher = ("if (( " + unsupported_version + " )); then "
                "printf '%s\\n' " + shlex.quote(version_notice) + " >&2; "
                "exec bash --login -i; fi; " + clock_preflight)
    # POSIX ENV provides a real login Bash with a separate initialization
    # descriptor. Leave POSIX mode BEFORE reading ordinary login profiles,
    # then compose their final PROMPT_COMMAND before its first execution.
    # No code passes through terminal input and no destination file is created.
    initialization = r'''set +o posix
[[ $_AS_BOOT_ERREXIT == 1 ]] || shopt -u inherit_errexit
if [[ $_AS_BOOT_ENV_SET == x ]]; then export ENV=$_AS_BOOT_ENV_VALUE; else unset ENV; fi
if [[ $_AS_BOOT_DEFAULT_HISTFILE == 1 ]]; then HISTFILE=$HOME/.bash_history; export -n HISTFILE; fi
exec {_AS_BOOT_FD}<&-
unset _AS_BOOT_FD _AS_BOOT_ERREXIT _AS_BOOT_ENV_SET _AS_BOOT_ENV_VALUE _AS_BOOT_DEFAULT_HISTFILE POSIXLY_CORRECT
[[ ! -r /etc/profile ]] || builtin source /etc/profile
for _as_startup_file in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
    if [[ -r $_as_startup_file ]]; then builtin source "$_as_startup_file"; break; fi
done
unset _as_startup_file
_AS_ORIGINAL_DEBUG=$(trap -p DEBUG)
''' + editor_payload
    launcher += r'''if [[ -o posix || ${POSIXLY_CORRECT+x} ]]; then
    printf '%s\n' 'atuin-ssh: existing POSIX Bash startup is unsupported for native integration; continuing with an ordinary Bash login shell' >&2
    exec bash --login -i
fi
if ! (unset ENV 2>/dev/null); then
    printf '%s\n' 'atuin-ssh: readonly ENV prevents temporary Bash initialization; continuing with an ordinary Bash login shell' >&2
    exec bash --login -i
fi
export _AS_BOOT_ENV_SET='' _AS_BOOT_ENV_VALUE='' _AS_BOOT_ERREXIT=0 _AS_BOOT_DEFAULT_HISTFILE=1
if [[ ${ENV+x} && $(declare -p ENV 2>/dev/null) =~ ^declare\ -[a-z]*x[a-z]*\ ENV= ]]; then
    export _AS_BOOT_ENV_SET=x _AS_BOOT_ENV_VALUE=$ENV
fi
if [[ $(declare -p BASHOPTS 2>/dev/null) =~ ^declare\ -[a-z]*x[a-z]*\ BASHOPTS= ]] && shopt -q inherit_errexit; then
    export _AS_BOOT_ERREXIT=1
fi
if [[ ${HISTFILE+x} && $(declare -p HISTFILE 2>/dev/null) =~ ^declare\ -[a-z]*x[a-z]*\ HISTFILE= ]]; then
    export _AS_BOOT_DEFAULT_HISTFILE=0
fi
unset _AS_BOOT_FD
if ! exec {_AS_BOOT_FD}< <(printf %s ''' + shlex.quote(initialization) + r''') || [[ ! -r /dev/fd/$_AS_BOOT_FD ]]; then
    [[ -z ${_AS_BOOT_FD-} ]] || exec {_AS_BOOT_FD}<&-
    unset _AS_BOOT_FD _AS_BOOT_ERREXIT _AS_BOOT_ENV_SET _AS_BOOT_ENV_VALUE _AS_BOOT_DEFAULT_HISTFILE
    printf '%s\n' 'atuin-ssh: temporary Bash initialization descriptor is unavailable; continuing with an ordinary Bash login shell' >&2
    exec bash --login -i
fi
export _AS_BOOT_FD
ENV=/dev/fd/$_AS_BOOT_FD exec bash --posix --login -i
'''
    shell_guard = ("" if force_bash else
                   "case ${SHELL##*/} in bash) ;; *) "
                   "printf '%s\\n' 'atuin-ssh: configured login shell is not Bash; native history integration is unavailable, continuing with the ordinary login shell' >&2; "
                   "exec \"$SHELL\" -l ;; esac; ")
    missing_bash_notice = ("printf '%s\\n' 'atuin-ssh: requested temporary Bash is unavailable; continuing with the ordinary login shell' >&2; "
                           if force_bash else "")
    fallback = (shell_guard + 'if command -v bash >/dev/null 2>&1; then exec bash -c '
                + shlex.quote(launcher) + '; else ' + missing_bash_notice + 'exec "$SHELL" -l; fi')
    return "sh -c " + shlex.quote(fallback)
