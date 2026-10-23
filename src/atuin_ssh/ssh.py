"""Conservative eligibility checks around the system OpenSSH client.

No argument is rewritten here. Unsupported or ambiguous invocations are executed
by the caller with the original argv. OpenSSH remains responsible for parsing,
configuration, authentication, forwarding, host keys, and exit status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import subprocess
from typing import Sequence


REAL_SSH = "/usr/bin/ssh"
# OpenSSH 10.x short-option grammar. Unknown options safely bypass enhancement.
_ARGUMENT = frozenset("BbcDEeFIiJLlmOopPQRSWw")
_FLAG = frozenset("46AaCfGgKkMNnqsTtVvXxYyZ")
_BYPASS = frozenset("NnfsTOGQVW")


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    destination: str | None
    enhanced: bool
    reason: str
    effective: dict[str, str] = field(default_factory=dict)
    destination_index: int | None = None


def plan_invocation(
    argv: Sequence[str],
    *,
    stdin_tty: bool = True,
    stdout_tty: bool = True,
    config_probe: bool = True,
    real_ssh: str = REAL_SSH,
) -> Invocation:
    """Determine whether an invocation is an ordinary interactive login.

    ``argv`` excludes the ssh executable. ``ssh -G`` evaluates the actual user
    configuration without connecting. If its result is unavailable or requests
    a different session, bypass rather than override that configuration. As with
    a normal invocation, user-configured ``Match exec`` may execute during this
    evaluation; callers should not perform additional redundant probes.
    """
    args = tuple(argv)
    destination: str | None = None
    destination_index: int | None = None

    def result(enhanced: bool, reason: str, effective: dict[str, str] | None = None) -> Invocation:
        return Invocation(args, destination, enhanced, reason, effective or {}, destination_index)

    if not stdin_tty or not stdout_tty:
        return result(False, "noninteractive terminal")
    if not args:
        return result(False, "no destination")
    i = 0
    options_finished = False
    while i < len(args):
        token = args[i]
        if options_finished or not token.startswith("-") or token == "-":
            destination = token
            destination_index = i
            if i != len(args) - 1:
                return result(False, "explicit remote command or trailing arguments")
            break
        if token == "--":
            options_finished = True
            i += 1
            continue
        if token.startswith("--"):
            return result(False, "unknown OpenSSH option")
        j = 1
        while j < len(token):
            flag = token[j]
            if flag not in _ARGUMENT and flag not in _FLAG:
                return result(False, "unknown OpenSSH option")
            if flag in _BYPASS:
                return result(False, f"OpenSSH -{flag} invocation")
            if flag in _ARGUMENT:
                if j + 1 == len(token):
                    i += 1
                    if i == len(args):
                        return result(False, f"missing argument for -{flag}")
                # The remainder (possibly empty) belongs to this option.
                break
            j += 1
        i += 1
    if destination is None or not destination or destination.startswith("-"):
        return result(False, "no unambiguous destination")
    if not config_probe:
        return result(True, "ordinary interactive shell (configuration not probed)")
    try:
        probe = subprocess.run(
            [real_ssh, "-G", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return result(False, "OpenSSH configuration evaluation unavailable")
    if probe.returncode:
        return result(False, "OpenSSH configuration evaluation failed")
    effective: dict[str, str] = {}
    for line in probe.stdout.splitlines():
        key, _, value = line.partition(" ")
        # Repeated IdentityFile/LocalForward/etc. remain entirely owned by ssh;
        # these diagnostic values are not used to reconstruct its arguments.
        effective.setdefault(key.lower(), value.strip())
    if effective.get("remotecommand", "none").lower() not in {"none", ""}:
        return result(False, "configured RemoteCommand", effective)
    if effective.get("requesttty", "auto").lower() in {"false", "no"}:
        return result(False, "configured RequestTTY=no", effective)
    if effective.get("sessiontype", "default").lower() != "default":
        return result(False, "configured SessionType", effective)
    if effective.get("stdinnull", "no").lower() in {"yes", "true"}:
        return result(False, "configured StdinNull", effective)
    if effective.get("forkafterauthentication", "no").lower() in {"yes", "true"}:
        return result(False, "configured ForkAfterAuthentication", effective)
    return result(True, "ordinary interactive shell", effective)


def enhanced_argv(invocation: Invocation, remote_command: str) -> list[str]:
    """Append a bootstrap only to an approved login and ensure a backend PTY."""
    if not invocation.enhanced:
        raise ValueError("cannot bootstrap a bypass invocation")
    # Before -- and the target: append-only options after a target can become a
    # remote command. A forced PTY reproduces the original interactive login.
    return [REAL_SSH, "-tt", *invocation.argv, remote_command]
