"""Pinned native Atuin integration.  No terminal emulation or alternative search UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

ATUIN_VERSION = "18.24.1"
ACCEPT_PREFIX = "__atuin_accept__:"
MAX_COMMAND_BYTES = 262_144
_QUERY_FDS: dict[str, int] = {}


@dataclass(frozen=True)
class Context:
    host: str
    user: str
    cwd: str
    session: str
    shell: str = "bash"
    workspace: str | None = None

    @classmethod
    def from_event(cls, event: dict) -> "Context":
        return cls(**{key: event[key] for key in ("host", "user", "cwd", "session")},
                   shell=event.get("shell", "bash"), workspace=event.get("workspace"))

    def environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if base is None else base)
        env.update(ATUIN_HOST_NAME=self.host, ATUIN_HOST_USER=self.user,
                   ATUIN_SESSION=self.session, ATUIN_SHELL=self.shell, PWD=self.cwd)
        # The source-reviewed native extension consumes remote workspace metadata.
        # Stock Atuin would discover Git in the hub's cwd: explicitly disable it.
        env["ATUIN_WORKSPACES"] = "false"
        env["ATUIN_AUTO_SYNC"] = "false"
        env["ATUIN_UPDATE_CHECK"] = "false"
        for name in ("ATUIN_HISTORY_AUTHOR", "ATUIN_HISTORY_AUTHOR_KIND", "ATUIN_HISTORY_INTENT"):
            env.pop(name, None)
        return env


@dataclass(frozen=True)
class WidgetResult:
    action: str
    command: str = ""


class NativeError(RuntimeError):
    """An operation failed; its diagnostic never contains a command body."""


class NativeAtuin:
    def __init__(self, binary: str = "atuin", helper: str = "atuin-ssh-native"):
        self.binary = binary
        self.helper = helper

    def version(self) -> str:
        return subprocess.check_output([self.binary, "--version"], text=True, timeout=5).strip()

    def prepare(self, context: Context, query: str = "", *, up: bool = False,
                keymap: str = "emacs", runtime_dir: str | Path | None = None,
                scope: str = "account") -> tuple[list[str], dict[str, str], Path]:
        """Prepare native TUI; the relay owns spawning, PTY, bytes, and cleanup.

        --result-file writes exact bytes (including trailing LF), unlike command
        substitution. Account/directory/workspace require the isolated native
        extension; a missing extension never silently broadens a search.
        """
        if keymap not in {"emacs", "vim-insert", "vim-normal", "auto"}:
            raise ValueError("unsupported Atuin keymap")
        if scope not in {"account", "host", "global", "session", "directory", "workspace"}:
            raise ValueError("stock Atuin cannot express requested scope")
        query_bytes = query.encode("utf-8", "strict")
        if len(query_bytes) > MAX_COMMAND_BYTES or b"\0" in query_bytes:
            raise ValueError("initial query exceeds supported representation")
        env = context.environment()
        env["ATUIN_QUERY"] = query
        env.pop("ATUIN_SSH_QUERY_FILE", None)
        search_binary = shutil.which("atuin-ssh-search")
        if search_binary:
            self.native("check", {})
            env["ATUIN_SSH_REMOTE_CONTEXT"] = "1"
            env["ATUIN_SSH_REMOTE_WORKSPACE"] = context.workspace or ""
            env["ATUIN_WORKSPACES"] = "true" if context.workspace else "false"
        elif scope in {"account", "directory", "workspace"}:
            raise NativeError("exact remote native search extension unavailable")
        fd, name = tempfile.mkstemp(prefix="atuin-ssh-result-", dir=runtime_dir)
        os.fchmod(fd, 0o600)
        os.close(fd)
        if len(query_bytes) > 65_536:
            if not search_binary:
                Path(name).unlink(missing_ok=True)
                raise NativeError("long initial query requires native compatibility component")
            query_fd = None
            try:
                query_fd = os.memfd_create("atuin-ssh-query", flags=os.MFD_CLOEXEC)
                with os.fdopen(os.dup(query_fd), "wb") as query_file:
                    query_file.write(query_bytes)
                os.lseek(query_fd, 0, os.SEEK_SET)
                os.set_inheritable(query_fd, True)
                _QUERY_FDS[name] = query_fd
                env["ATUIN_QUERY"] = ""
                env["ATUIN_SSH_QUERY_FILE"] = f"/proc/self/fd/{query_fd}"
            except OSError:
                Path(name).unlink(missing_ok=True)
                if query_fd is not None:
                    os.close(query_fd)
                raise
        argv = [search_binary or self.binary, "search", "-i", "--filter-mode", scope,
                "--keymap-mode", keymap, "--result-file", name]
        if up:
            argv.append("--shell-up-key-binding")
        return argv, env, Path(name)

    @staticmethod
    def result(path: str | Path, returncode: int = 0) -> WidgetResult:
        target = Path(path)
        try:
            if returncode or target.stat().st_size > MAX_COMMAND_BYTES:
                return WidgetResult("cancel")
            raw = target.read_bytes()
            if not raw or b"\0" in raw:
                return WidgetResult("cancel")
            result = raw.decode("utf-8", "strict")
            if result.startswith(ACCEPT_PREFIX):
                return WidgetResult("accept", result[len(ACCEPT_PREFIX):])
            return WidgetResult("insert", result)
        except (OSError, UnicodeError):
            return WidgetResult("cancel")
        finally:
            NativeAtuin.cleanup(target)

    parse_result = result

    @staticmethod
    def cleanup(path: str | Path):
        target = Path(path)
        target.unlink(missing_ok=True)
        query_fd = _QUERY_FDS.pop(str(target), None)
        if query_fd is not None:
            os.close(query_fd)

    def native(self, operation: str, event: dict, *, timeout: float = 10) -> dict:
        if not shutil.which(self.helper):
            raise NativeError("version-pinned native adapter unavailable")
        try:
            reply = subprocess.run([self.helper, operation], input=json.dumps(event),
                                   text=True, encoding="utf-8", capture_output=True,
                                   timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NativeError("native adapter unavailable or timed out") from exc
        if reply.returncode:
            # Upstream errors may embed untrusted command text. Never forward them.
            raise NativeError("native adapter refused operation")
        try:
            result = json.loads(reply.stdout)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, TypeError) as exc:
            raise NativeError("invalid native adapter response") from exc

    def allowed(self, event: dict) -> bool:
        return self.native("filter", event).get("allowed") is True
