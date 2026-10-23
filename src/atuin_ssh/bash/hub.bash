# Loaded after native Atuin. Do not replace a user's existing ssh function.
if [[ $- == *i* && -z ${ATUIN_SSH_INITIALIZED-} ]]; then
    if ! declare -F ssh >/dev/null; then
        ssh() {
            local _as_disable_r=${ATUIN_SSH_DISABLE_CTRL_R:-0}
            local _as_disable_up=${ATUIN_SSH_DISABLE_UP:-0}
            [[ ${__atuin_bind_ctrl_r-true} != false ]] || _as_disable_r=1
            [[ ${__atuin_bind_up_arrow-true} != false ]] || _as_disable_up=1
            ATUIN_SSH_DISABLE_CTRL_R=$_as_disable_r ATUIN_SSH_DISABLE_UP=$_as_disable_up command atuin-ssh connect -- "$@"
        }
        _atuin_ssh_wrapper_definition=$(declare -f ssh)
        export ATUIN_SSH_INITIALIZED=1
    else
        printf '%s\n' 'atuin-ssh: existing ssh function preserved; use atuin-ssh connect explicitly.' >&2
    fi
fi
atuin_ssh_disable() {
    if [[ ${ATUIN_SSH_INITIALIZED-} == 1 ]]; then
        if [[ $(declare -f ssh) == "${_atuin_ssh_wrapper_definition-}" ]]; then
            unset -f ssh
        fi
        unset _atuin_ssh_wrapper_definition
        unset ATUIN_SSH_INITIALIZED
    fi
}
atuin_ssh_enable() { eval "$(command atuin-ssh init bash)"; }
