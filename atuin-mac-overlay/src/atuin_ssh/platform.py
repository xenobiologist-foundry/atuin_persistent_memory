"""POSIX descriptors and native Darwin PTY spawning; no Python after fork."""
from __future__ import annotations
import os
from pathlib import Path
import pty
import signal
import sys
import termios


def resources() -> Path:
    return Path(os.environ.get("ATUIN_LAYER_ROOT", Path(__file__).resolve().parents[2])) / "resources"


def state_root() -> Path:
    return Path(os.environ.get("ATUIN_SSH_STATE_DIR", str(
        Path.home() / "Library/Application Support/AtuinMacOverlay/bridge")))


def pipe(*, nonblocking=False):
    read, write = os.pipe()
    if nonblocking:
        os.set_blocking(read, False)
        os.set_blocking(write, False)
    return read, write


def spawn(argv, env, attrs, size):
    """posix_spawn execs a tiny native controlling-terminal adapter.

    Only intentionally inheritable READY/query descriptors survive exec. All
    ordinary Python descriptors are CLOEXEC. No Python or system-framework
    calls run between fork and exec, including with active native workers.
    """
    helper = resources().parent / "bin/atuin-layer-pty"
    master, slave = pty.openpty()
    try:
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        termios.tcsetwinsize(slave, size)
        actions = [(os.POSIX_SPAWN_DUP2, slave, fd) for fd in (0, 1, 2)]
        actions.extend([(os.POSIX_SPAWN_CLOSE, master), (os.POSIX_SPAWN_CLOSE, slave)])
        pid = os.posix_spawn(str(helper), [str(helper), *argv], env,
                             file_actions=actions, setsigmask=(),
                             setsigdef=(signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP,
                                        signal.SIGTTIN, signal.SIGTTOU, signal.SIGHUP))
        os.set_blocking(master, False)
        return pid, master
    except BaseException:
        os.close(master)
        raise
    finally:
        os.close(slave)
