"""A real Linux workstation PTY, intentionally independent of the bridge relay."""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time


class PTYClient:
    def __init__(self, argv: list[str], *, rows: int = 36, columns: int = 140,
                 env: dict[str, str] | None = None):
        self.pid, self.fd = pty.fork()
        if not self.pid:
            os.environ["TERM"] = "xterm-256color"
            os.environ["LC_ALL"] = "C.UTF-8"
            if env:
                os.environ.update(env)
            os.execvpe(argv[0], argv, os.environ)
        self.buffer = bytearray()
        self.transcript = bytearray()
        self.query_tail = b""
        self.closed = False
        self.resize(rows, columns)

    def resize(self, rows: int, columns: int) -> None:
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        os.kill(self.pid, signal.SIGWINCH)

    def send(self, data: bytes | str) -> None:
        if isinstance(data, str):
            data = data.encode()
        view = memoryview(data)
        while view:
            _, writable, _ = select.select([], [self.fd], [], 5)
            if not writable:
                raise TimeoutError("workstation PTY stalled")
            count = os.write(self.fd, view)
            view = view[count:]

    def read(self, timeout: float = .05) -> bytes:
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return b""
        try:
            data = os.read(self.fd, 65536)
        except OSError as error:
            if error.errno == errno.EIO:
                self.closed = True
                return b""
            raise
        if not data:
            self.closed = True
        self.buffer.extend(data)
        # Disposable test transcripts are held in memory only. They are never a
        # runtime logging feature or a fixture containing production commands.
        self.transcript.extend(data)
        # A streaming recognizer must answer each terminal query exactly once.
        # Keep only an unfinished query prefix across reads, never a completed
        # query that could be answered again when unrelated output follows.
        queries = {b"\x1b[6n": b"\x1b[1;1R", b"\x1b[c": b"\x1b[?1;2c"}
        pending = self.query_tail + data
        for found in re.finditer(rb"\x1b\[6n|\x1b\[c", pending):
            self.send(queries[found[0]])
        self.query_tail = b""
        for length in range(1, 4):
            suffix = pending[-length:]
            if any(query.startswith(suffix) and len(suffix) < len(query) for query in queries):
                self.query_tail = suffix
        return data

    def expect(self, pattern: bytes | re.Pattern[bytes], timeout: float = 10) -> re.Match[bytes]:
        expression = re.compile(re.escape(pattern)) if isinstance(pattern, bytes) else pattern
        deadline = time.monotonic() + timeout
        while True:
            # Match against an immutable snapshot. Match groups must remain
            # valid after consuming the corresponding mutable receive buffer.
            found = expression.search(bytes(self.buffer))
            if found:
                del self.buffer[:found.end()]
                return found
            if self.closed or time.monotonic() >= deadline:
                # Only disposable test shell data appears here.
                raise AssertionError(f"PTY expected {expression.pattern!r}; tail={bytes(self.buffer[-6000:])!r}")
            self.read(min(.1, max(0, deadline-time.monotonic())))

    def drain(self, seconds: float = .15) -> bytes:
        start = len(self.buffer)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.closed:
            self.read(min(.05, deadline-time.monotonic()))
        return bytes(self.buffer[start:])

    def close(self) -> None:
        if self.closed:
            os.close(self.fd)
            return
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            child, _ = os.waitpid(self.pid, os.WNOHANG)
            if child:
                break
            self.read(.05)
        else:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(self.pid, 0)
        os.close(self.fd)
        self.closed = True
