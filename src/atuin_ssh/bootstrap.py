"""In-memory Bash bootstrap. Never send the payload as interactive keystrokes."""
from importlib.resources import files
import os
import shlex


def remote_command(nonce: str, session: str) -> str:
    payload = files("atuin_ssh").joinpath("bash/remote.bash").read_text()
    payload = payload.replace("@NONCE@", nonce).replace("@SESSION@", session)
    payload = payload.replace("@BIND_CTRL_R@", "0" if os.environ.get("ATUIN_SSH_DISABLE_CTRL_R") == "1" else "1")
    payload = payload.replace("@BIND_UP@", "0" if os.environ.get("ATUIN_SSH_DISABLE_UP") == "1" else "1")
    # An exported first-prompt function lets a real login Bash load its normal
    # profiles exactly once. A profile replacing PROMPT_COMMAND can disable the
    # bootstrap, in which case this remains an ordinary login shell.
    install = "unset -f _as_boot; [[ ${PROMPT_COMMAND-} != _as_boot ]] || unset PROMPT_COMMAND; " + payload
    launcher = ("if [[ ${SHELL##*/} != bash ]]; then exec \"$SHELL\" -l; fi; "
                "_as_boot() { " + install + "\n}; export -f _as_boot; "
                "export PROMPT_COMMAND=_as_boot; exec bash --login -i")
    fallback = 'if command -v bash >/dev/null 2>&1; then exec bash -c ' + shlex.quote(launcher) + '; else exec "$SHELL" -l; fi'
    return "sh -c " + shlex.quote(fallback)
