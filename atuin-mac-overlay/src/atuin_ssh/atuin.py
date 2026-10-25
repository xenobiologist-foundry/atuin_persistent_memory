"""Pinned native Atuin integration.  No terminal emulation or alternative search UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass

ATUIN_VERSION = "18.24.1"
ACCEPT_PREFIX = "__atuin_accept__:"
INSERT_PREFIX = "__atuin_insert__:"
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

    def suggest(self, context: Context, prefix: str) -> str:
        """Return one exact-account prefix match, using native search only.

        Called by a bounded background worker while the destination editor owns
        its fenced reply channel. No search state or command bodies are cached.
        """
        if not prefix or len(prefix.encode("utf-8")) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in prefix):
            return ""
        binary = shutil.which("atuin-ssh-search")
        if not binary:
            return ""
        compatibility = self.native("check", {}, timeout=2)
        database_path = compatibility.get("history_db_path")
        if not isinstance(database_path, str) or not database_path:
            return ""
        environment = context.environment()
        environment.update(ATUIN_QUERY=prefix, ATUIN_SSH_REMOTE_CONTEXT="1",
                           ATUIN_SSH_REMOTE_WORKSPACE=context.workspace or "")
        try:
            # Native command formatting trims whitespace. Select the native
            # UUID, then read that exact bounded row from its checked SQLite
            # view without altering any database or record-store state.
            with subprocess.Popen([binary, "search", "--format", "{uuid}", "--limit", "1",
                                   "--search-mode", "prefix", "--filter-mode", "account"],
                                  env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL) as child:
                output = bytearray()
                deadline = time.monotonic() + 2
                try:
                    while len(output) <= 128:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not select.select([child.stdout], [], [], remaining)[0]:
                            return ""
                        chunk = os.read(child.stdout.fileno(), min(129 - len(output), 128))
                        if not chunk:
                            break
                        output.extend(chunk)
                    if (len(output) > 128 or not output.endswith(b"\n")
                            or child.wait(timeout=max(.01, deadline - time.monotonic()))):
                        return ""
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
            identifier = output[:-1].decode("ascii", "strict")
            if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
                return ""
            uri = Path(database_path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=.2)) as database:
                row = database.execute("SELECT command FROM history WHERE id=? AND hostname=? "
                                       "AND deleted_at IS NULL AND length(CAST(command AS BLOB))<=65536",
                                       (identifier, context.host + ":" + context.user)).fetchone()
            if row is None:
                return ""
            command = row[0]
            if (not command.startswith(prefix) or command == prefix
                    or any(ord(c) < 32 or ord(c) == 127 for c in command)):
                return ""
            return command
        except (OSError, UnicodeError, sqlite3.Error, subprocess.TimeoutExpired):
            return ""

    def prepare(self, context: Context, query: str = "", *, up: bool = False,
                keymap: str = "emacs", runtime_dir: str | Path | None = None,
                scope: str = "account") -> tuple[list[str], dict[str, str], Path]:
        """Prepare native TUI; the relay owns spawning, PTY, bytes, and cleanup.

        --result-file writes exact bytes (including trailing LF), unlike command
        substitution. Every remote widget requires the isolated extension's
        unambiguous result tags; a missing component fails before allocation.
        """
        if keymap not in {"emacs", "vim-insert", "vim-normal", "auto"}:
            raise ValueError("unsupported Atuin keymap")
        if scope not in {"account", "host", "global", "session", "directory", "workspace"}:
            raise ValueError("unsupported native search scope")
        query_bytes = query.encode("utf-8", "strict")
        if len(query_bytes) > MAX_COMMAND_BYTES or b"\0" in query_bytes:
            raise ValueError("initial query exceeds supported representation")
        env = context.environment()
        env["ATUIN_QUERY"] = query
        env.pop("ATUIN_SSH_QUERY_FD", None)
        search_binary = shutil.which("atuin-ssh-search")
        if search_binary:
            self.native("check", {})
            env["ATUIN_SSH_REMOTE_CONTEXT"] = "1"
            env["ATUIN_SSH_RESULT_PROTOCOL"] = "2"
            env["ATUIN_SSH_REMOTE_WORKSPACE"] = context.workspace or ""
            env["ATUIN_WORKSPACES"] = "true" if context.workspace else "false"
        else:
            raise NativeError("remote native search compatibility component unavailable")
        fd, name = tempfile.mkstemp(prefix="atuin-ssh-result-", dir=runtime_dir)
        os.fchmod(fd, 0o600)
        os.close(fd)
        if len(query_bytes) > 65_536:
            if not search_binary:
                Path(name).unlink(missing_ok=True)
                raise NativeError("long initial query requires native compatibility component")
            query_fd = None
            try:
                # An anonymous local socket holds the bounded query in kernel memory.
                # SO_SNDBUF is sized before writing; no query touches disk.
                import socket
                reader, writer = socket.socketpair()
                try:
                    writer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, MAX_COMMAND_BYTES * 2)
                    writer.settimeout(0.2)
                    writer.sendall(query_bytes)
                    writer.shutdown(socket.SHUT_WR)
                    query_fd = reader.detach()
                finally:
                    reader.close()
                    writer.close()
                os.set_inheritable(query_fd, True)
                _QUERY_FDS[name] = query_fd
                env["ATUIN_QUERY"] = ""
                env["ATUIN_SSH_QUERY_FD"] = str(query_fd)
            except OSError:
                Path(name).unlink(missing_ok=True)
                if query_fd is not None:
                    os.close(query_fd)
                raise
        argv = [search_binary, "search", "-i", "--filter-mode", scope,
                "--keymap-mode", keymap, "--result-file", name]
        if up:
            argv.append("--shell-up-key-binding")
        return argv, env, Path(name)

    @staticmethod
    def result(path: str | Path, returncode: int = 0) -> WidgetResult:
        target = Path(path)
        try:
            if returncode or target.stat().st_size > MAX_COMMAND_BYTES + max(len(ACCEPT_PREFIX), len(INSERT_PREFIX)):
                return WidgetResult("cancel")
            raw = target.read_bytes()
            if not raw or b"\0" in raw:
                return WidgetResult("cancel")
            result = raw.decode("utf-8", "strict")
            if result.startswith(INSERT_PREFIX):
                command = result[len(INSERT_PREFIX):]
                if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
                    return WidgetResult("cancel")
                return WidgetResult("insert", command)
            if result.startswith(ACCEPT_PREFIX):
                command = result[len(ACCEPT_PREFIX):]
                if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
                    return WidgetResult("cancel")
                return WidgetResult("accept", command)
            if len(raw) > MAX_COMMAND_BYTES:
                return WidgetResult("cancel")
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

    def native(self, operation: str, event: dict, *, timeout: float | None = None) -> dict:
        if not shutil.which(self.helper):
            raise NativeError("version-pinned native adapter unavailable")
        if timeout is None:
            # Stable-ID recovery decrypts the native record stream. A measured
            # million-record scan takes longer than the ordinary CLI deadline.
            # Recovery runs in background workers, never on the relay byte path.
            timeout = 120 if event.get("reconcile") else 10
        try:
            reply = subprocess.run([self.helper, operation], input=json.dumps(event, ensure_ascii=False),
                                   text=True, encoding="utf-8", capture_output=True,
                                   timeout=timeout, check=False)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
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
        return self.privacy(event).get("allowed") is True

    def privacy(self, event: dict) -> dict:
        return self.native("filter", event)

    def batch(self, operation: str, events: list[dict]) -> list[dict]:
        """Run bounded native batches, retaining input order and exact IDs.

        A refused batch may have committed a prefix before failing. Callers must
        durably mark all submitted entries before invocation and reconcile every
        uncertain entry on retry; no success is inferred from process failure.
        """
        if operation not in {"filter", "probe", "import"}:
            raise ValueError("unsupported native batch operation")
        results: list[dict] = []
        pending: list[dict] = []
        size = len('{"events": []}')

        def flush():
            nonlocal pending, size
            if not pending:
                return
            timeout = 120 if any(event.get("reconcile") for event in pending) else 10
            reply = self.native(operation + "_batch", {"events": pending}, timeout=timeout)
            values = reply.get("results")
            if not isinstance(values, list) or len(values) != len(pending) or not all(isinstance(value, dict) for value in values):
                raise NativeError("invalid native batch response")
            results.extend(values)
            pending = []
            size = len('{"events": []}')

        for event in events:
            encoded_size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
            if encoded_size + len('{"events": []}') > 1_048_576:
                # JSON escapes can expand a valid 256 KiB control-heavy command
                # beyond the batch budget. Preserve the existing single-event
                # representation limit rather than discarding that command.
                if encoded_size > 2_097_152:
                    raise NativeError("event exceeds native representation bound")
                flush()
                timeout = 120 if event.get("reconcile") else 10
                results.append(self.native(operation, event, timeout=timeout))
                continue
            # Recovery may decrypt the complete native record stream for this
            # ID. Give each uncertain entry its own bounded recovery deadline.
            if event.get("reconcile"):
                flush()
                pending = [event]
                size += encoded_size
                flush()
                continue
            extra = encoded_size + (2 if pending else 0)
            if len(pending) == 64 or size + extra > 1_048_576:
                flush()
                extra = encoded_size
            pending.append(event)
            size += extra
        flush()
        return results

    def privacy_batch(self, events: list[dict]) -> list[dict]:
        return self.batch("filter", events)
