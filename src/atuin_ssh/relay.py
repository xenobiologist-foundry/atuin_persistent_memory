"""One foreground owner, two PTYs, real OpenSSH and native Atuin.

The front terminal always stays with the relay. Only one child receives input.
UI output uses a separate PTY so remote background output cannot corrupt it.
"""
from __future__ import annotations
import errno
import fcntl
import os
import pty
import select
import signal
import sys
import termios
import time
import tty
import uuid
from collections import deque
from enum import Enum

from .atuin import Context, NativeAtuin
from .bootstrap import remote_command
from .protocol import Frame, FrameParser, response

LIMIT = 1_048_576


class State(Enum):
    BOOTSTRAP = "authentication/bootstrap"
    PROMPT = "instrumented shell"
    RUNNING = "command running"
    WAIT = "widget request/wait"
    UI = "local widget active"
    RESTORE = "restore"
    DEGRADED = "degraded"
    CLOSING = "closing"


def _spawn(argv, env, attrs, size):
    pid, master = pty.fork()
    if pid == 0:
        try:
            termios.tcsetattr(0, termios.TCSANOW, attrs)
            termios.tcsetwinsize(0, size)
            os.execvpe(argv[0], argv, env)
        except BaseException as exc:
            os.write(2, f"atuin-ssh child: {exc}\r\n".encode())
            os._exit(127)
    os.set_blocking(master, False)
    return pid, master


def _read(fd):
    try:
        return os.read(fd, 65536)
    except OSError as exc:
        if exc.errno == errno.EIO:
            return b""
        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise


def _write(fd, buffer):
    if buffer:
        try:
            count = os.write(fd, buffer[:65536])
            del buffer[:count]
        except BlockingIOError:
            pass


class Relay:
    def __init__(self, argv, *, native=None, outbox=None):
        self.nonce = uuid.uuid4().hex
        self.session = uuid.uuid7().hex
        self.argv = ["/usr/bin/ssh", *argv, remote_command(self.nonce, self.session)]
        # Force a remote PTY only for eligible shell invocations.
        self.argv.insert(1, "-tt")
        self.native = native or NativeAtuin()
        self.outbox = outbox
        self.parser = FrameParser(self.nonce)
        self.state = State.BOOTSTRAP
        self.request = None
        self.last_request = 0
        self.completed_request = 0
        self.reply_id = None
        self.widget_cancelled = False
        self.ui = None
        self.to_backend = bytearray()
        self.to_front = bytearray()
        self.to_ui = bytearray()
        self.held_input = bytearray()
        self.held_output = bytearray()
        self.metrics = deque(maxlen=256)  # durations only; bounded, never transcripts

    def notice(self, text):
        if len(self.to_front) < LIMIT:
            self.to_front.extend(("\r\natuin-ssh: " + text + "\r\n").encode())

    def frame(self, event):
        fields = event.fields
        if event.kind == "ABORT" and len(fields) == 2 and fields[1] == self.session and fields[0].isdigit():
            req = int(fields[0])
            if req <= self.completed_request or (self.reply_id == fields[0]):
                return
            if self.request and fields[0] != self.request[0]:
                return
            self.last_request = max(self.last_request, req)
            if self.ui:
                self.widget_cancelled = True
                try:
                    os.kill(self.ui[0], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                self.send_response(fields[0], "cancel")
        elif event.kind == "RELEASE" and len(fields) == 2 and fields[1] == self.session and fields[0] == self.reply_id:
            self.completed_request = int(fields[0])
            self.reply_id = None
            self.request = None
            self.state = State.PROMPT
            self.to_backend.extend(self.held_input)
            self.held_input.clear()
        elif event.kind == "REQUEST" and self.state not in {State.WAIT, State.UI, State.RESTORE}:
            if len(fields) not in {10, 11} or not fields[0].isdigit():
                return
            req, key, line, point, mark, keymap, host, user, cwd, session = fields[:10]
            if session != self.session or key not in {"up", "search"}:
                return
            if int(req) <= self.last_request:
                return
            self.last_request = int(req)
            if len(line.encode("utf-8", "surrogateescape")) > 262144 or not point.isdigit():
                self.send_response(req, "cancel")
                return
            self.request = fields
            self.request_time = time.monotonic()
            self.state = State.WAIT
            self.to_backend.extend(f"!{self.nonce}:{req}:FENCE\n".encode())
        elif event.kind == "HANDOVER" and self.state == State.WAIT:
            if len(fields) != 2 or fields[0] != self.request[0]:
                return
            # Only the remote callback can assert ownership. It returns all
            # type-ahead preceding the fence in the SSH input byte stream.
            self.open_widget(fields[1].encode("utf-8", "surrogateescape"))
        elif event.kind == "HELLO" and self.state == State.BOOTSTRAP:
            self.state = State.PROMPT
        elif event.kind == "PROMPT" and not self.ui:
            self.state = State.PROMPT
        elif event.kind == "START":
            self.state = State.RUNNING
            if self.outbox:
                self.outbox_event(event)
        elif event.kind == "END":
            if self.outbox:
                self.outbox_event(event)
        elif event.kind == "DEGRADED":
            self.state = State.DEGRADED
            self.notice("destination hooks incompatible; command capture is degraded")

    def outbox_event(self, event):
        try:
            if event.kind == "START" and len(event.fields) == 7:
                ident, command, host, user, cwd, session, timestamp = event.fields
                if session != self.session or not ident.startswith(self.session + ":") or not ident[len(self.session)+1:].isdigit():
                    return
                accepted = self.outbox.submit({"type": "start", "sequence": event.sequence, "command_id": ident, "command": command,
                                    "host": host, "user": user, "cwd": cwd, "session": session,
                                    "shell": "bash", "timestamp": timestamp})
                if not accepted:
                    self.notice("history ingress full; this event has not been durably accepted")
            elif event.kind == "END" and len(event.fields) == 3:
                ident, status, timestamp = event.fields
                if not ident.startswith(self.session + ":") or not ident[len(self.session)+1:].isdigit():
                    return
                if not self.outbox.submit({"type": "end", "command_id": ident, "status": int(status), "timestamp": timestamp}):
                    self.notice("history ingress full; completion has not been durably accepted")
        except Exception:
            self.notice("history persistence unavailable; SSH remains active (run atuin-ssh doctor)")

    def send_response(self, req, action, command=""):
        if self.reply_id == req or int(req) <= self.completed_request:
            return
        self.to_backend.extend(response(self.nonce, req, action, command))
        self.reply_id = req
        self.state = State.RESTORE

    def open_widget(self, typeahead):
        req, key, line, point, mark, keymap, host, user, cwd, session = self.request[:10]
        workspace = self.request[10] if len(self.request) == 11 else None
        path = None
        try:
            if self.outbox:
                if not self.outbox.barrier(timeout=0.5):
                    self.notice("history writer is delayed; pending history may be absent")
            keymaps = {"vi-command": "vim-normal", "vi-insert": "vim-insert"}
            argv, env, path = self.native.prepare(Context(host, user, cwd, session, workspace=workspace), line,
                                                 up=key == "up", keymap=keymaps.get(keymap, "emacs"))
            pid, fd = _spawn(argv, env, self.raw_attrs, self.size)
            self.ui = (pid, fd, path)
            self.widget_cancelled = False
            self.to_ui.extend(typeahead)
            self.to_ui.extend(self.held_input)
            self.held_input.clear()
            self.state = State.UI
            self.metrics.append({"request_to_ui_ms": (time.monotonic() - self.request_time) * 1000})
        except Exception:
            if path is not None:
                try:
                    self.native.cleanup(path)
                except OSError:
                    pass
            self.notice("native Atuin unavailable; original editor restored")
            self.send_response(req, "cancel")

    def close_widget(self, status):
        self.state = State.RESTORE
        pid, fd, path = self.ui
        # Drain the native alternate-screen teardown before remote redraw.
        while len(self.to_front) < LIMIT:
            output = _read(fd)
            if not output:
                break
            self.to_front.extend(output)
        os.close(fd)
        self.ui = None
        result = self.native.result(path, os.waitstatus_to_exitcode(status))
        self.send_response(self.request[0], "cancel" if self.widget_cancelled else result.action, result.command or "")
        self.metrics.append({"widget_duration_ms": (time.monotonic()-self.request_time)*1000})
        # Output received while UI active is replayed in original byte order.
        self.to_front.extend(self.held_output)
        self.held_output.clear()
        self.to_ui.clear()

    def run(self):
        self.front = sys.stdin.fileno()
        self.output = sys.stdout.fileno()
        attrs = termios.tcgetattr(self.front)
        self.size = termios.tcgetwinsize(self.front)
        if not all(self.size):
            self.size = (24, 80)
        saved_flags = {fd: fcntl.fcntl(fd, fcntl.F_GETFL) for fd in {self.front, self.output}}
        previous = {}
        self.stopping = False
        self.resized = False
        for sig in (signal.SIGWINCH, signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda signum, frame: setattr(self, "resized" if signum == signal.SIGWINCH else "stopping", True))
        backend_pid = backend_fd = None
        try:
            backend_pid, backend_fd = _spawn(self.argv, os.environ.copy(), attrs, self.size)
            tty.setraw(self.front, termios.TCSANOW)
            self.raw_attrs = termios.tcgetattr(self.front)
            os.set_blocking(self.front, False)
            os.set_blocking(self.output, False)
            backend_eof = False
            backend_status = None
            parser_flushed = False
            while not self.stopping:
                if self.resized:
                    self.resized = False
                    self.size = termios.tcgetwinsize(self.front)
                    termios.tcsetwinsize(backend_fd, self.size)
                    if self.ui:
                        termios.tcsetwinsize(self.ui[1], self.size)
                if self.state == State.WAIT and time.monotonic()-self.request_time > 35:
                    self.notice("widget ownership handshake timed out; restoring callback")
                    self.send_response(self.request[0], "cancel")
                reads, writes = [], []
                if len(self.to_backend)+len(self.held_input)+len(self.to_ui) < LIMIT:
                    reads.append(self.front)
                if not backend_eof and (len(self.held_output) if self.ui else len(self.to_front)) < LIMIT:
                    reads.append(backend_fd)
                if self.ui and len(self.to_front)<LIMIT:
                    reads.append(self.ui[1])
                if self.to_front:
                    writes.append(self.output)
                if self.to_backend and not backend_eof:
                    writes.append(backend_fd)
                if self.ui and self.to_ui:
                    writes.append(self.ui[1])
                readable, writable, _ = select.select(reads, writes, [], 0.05)
                for fd in writable:
                    try:
                        _write(fd, self.to_front if fd == self.output else self.to_backend if fd == backend_fd else self.to_ui)
                    except OSError as exc:
                        if fd == backend_fd and exc.errno == errno.EIO:
                            backend_eof = True
                        elif fd != (self.ui[1] if self.ui else None):
                            raise
                for fd in readable:
                    data = _read(fd)
                    if data is None:
                        continue
                    if fd == self.front:
                        if not data:
                            self.stopping = True
                        elif self.ui:
                            self.to_ui.extend(data)
                        elif self.state in {State.WAIT, State.RESTORE}:
                            self.held_input.extend(data)
                        else:
                            self.to_backend.extend(data)
                    elif fd == backend_fd:
                        if not data:
                            backend_eof = True
                        else:
                            for item in self.parser.feed(data):
                                if isinstance(item, bytes):
                                    (self.held_output if self.ui else self.to_front).extend(item)
                                else:
                                    self.frame(item)
                    elif data:
                        self.to_front.extend(data)
                if self.ui:
                    if backend_eof:
                        self.widget_cancelled = True
                        try:
                            os.kill(self.ui[0], signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    ended, status = os.waitpid(self.ui[0], os.WNOHANG)
                    if ended:
                        self.close_widget(status)
                if backend_eof and not self.ui and not parser_flushed:
                    self.to_front.extend(self.parser.finish())
                    parser_flushed = True
                if backend_status is None:
                    ended, status = os.waitpid(backend_pid, os.WNOHANG | os.WUNTRACED)
                    if ended:
                        if os.WIFSTOPPED(status):
                            termios.tcsetattr(self.front, termios.TCSANOW, attrs)
                            os.kill(os.getpid(), signal.SIGSTOP)
                            tty.setraw(self.front, termios.TCSANOW)
                            os.kill(backend_pid, signal.SIGCONT)
                        else:
                            backend_status = status
                if backend_eof and backend_status is not None and not self.ui and not self.to_front:
                    return os.waitstatus_to_exitcode(backend_status)
            return 255
        finally:
            self.state = State.CLOSING
            if self.ui:
                try:
                    os.kill(self.ui[0], signal.SIGHUP)
                    os.close(self.ui[1])
                except OSError:
                    pass
                try:
                    self.native.cleanup(self.ui[2])
                except OSError:
                    pass
            if backend_fd is not None:
                try:
                    os.close(backend_fd)
                except OSError:
                    pass
            if backend_pid is not None:
                try:
                    os.kill(backend_pid, signal.SIGHUP)
                except ProcessLookupError:
                    pass
            try:
                termios.tcsetattr(self.front, termios.TCSANOW, attrs)
            except termios.error:
                pass  # The workstation terminal may already be disconnected.
            for fd, flags in saved_flags.items():
                try:
                    fcntl.fcntl(fd, fcntl.F_SETFL, flags)
                except OSError:
                    pass
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if self.outbox:
                self.outbox.close()
