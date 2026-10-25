"""One foreground owner, two PTYs, real OpenSSH and native Atuin.

The front terminal always stays with the relay. Only one child receives input.
UI output uses a separate PTY so remote background output cannot corrupt it.
"""
from __future__ import annotations
import errno
import fcntl
import os
import pty
import re
import select
import signal
import sys
import termios
import time
import tty
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

from .atuin import Context, NativeAtuin
from .bootstrap import remote_command
from .protocol import Frame, FrameParser, response

LIMIT = 1_048_576

# Render only known local explanations. Remote text can contain terminal
# controls or command data and must never be copied into a diagnostic notice.
DEGRADED_REASONS = {
    "Accepted command exceeds capture bound.":
        "accepted command exceeds the 256 KiB capture bound; this command was not recorded",
    "Accepted history expansion unavailable; command capture skipped.":
        "Bash history expansion unavailable; this command was not recorded",
    "Complex HISTIGNORE: repeated-command capture unavailable; native history exclusions preserved.":
        "complex HISTIGNORE pattern prevents repeated-command capture; native exclusions were preserved",
    "DEBUG hook replaced: capture and native hub keys disabled for this shell.":
        "destination DEBUG hook was replaced; capture and native history keys are disabled",
    "Existing DEBUG trap/functrace: capture and native hub keys unavailable for this shell.":
        "destination has an existing DEBUG trap or functrace; capture and native history keys are disabled",
}


class State(Enum):
    BOOTSTRAP = "authentication/bootstrap"
    PROMPT = "instrumented shell"
    RUNNING = "command running"
    WAIT = "widget request/wait"
    UI = "local widget active"
    RESTORE = "restore"
    DEGRADED = "degraded"
    CLOSING = "closing"


from .platform import spawn as _spawn, pipe, state_root


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
    def __init__(self, argv, *, native=None, outbox=None, connection=None, force_bash=False, autosuggest=None):
        self.nonce = uuid.uuid4().hex
        self.session = uuid.uuid7().hex
        self.bundle = None
        if autosuggest is True or (autosuggest is None and os.environ.get("ATUIN_SSH_REMOTE_AUTOSUGGEST", "1") != "0"):
            from .blesh import BundleError, load_bundle
            try:
                self.bundle = load_bundle()
            except (OSError, ValueError, BundleError):
                pass  # A missing/incompatible optional editor keeps GNU Readline.
        self.argv = ["/usr/bin/ssh", *argv, remote_command(self.nonce, self.session, force_bash=force_bash,
                                                       bundle=self.bundle)]
        # Force a remote PTY only for eligible shell invocations.
        self.argv.insert(1, "-tt")
        self.native = native or NativeAtuin()
        self.outbox = outbox
        self.connection_registry = None
        if connection:
            try:
                from .context import ConnectionRegistry
                self.connection_registry = ConnectionRegistry()
                self.connection_registry.register(self.session, connection.destination, connection.effective)
            except Exception:
                self.connection_registry = None
        self.parser = FrameParser(self.nonce)
        self.state = State.BOOTSTRAP
        self.handshake_seen = False
        self.request = None
        self.last_request = 0
        self.completed_request = 0
        self.reply_id = None
        self.widget_cancelled = False
        self.ui = None
        self.ready_fd = None
        self.ready_buffer = bytearray()
        self.ui_ready = False
        self.ui_startup_input = bytearray()
        self.ui_negotiation = bytearray()
        self.ui_query_tail = b""
        self.ui_control_tail = b""
        self.ui_modes = {}
        self.ui_keyboard_depth = 0
        self.ui_expected = {"cpr": 0, "da": 0, "keyboard": 0}
        self.to_backend = bytearray()
        self.to_front = bytearray()
        self.to_ui = bytearray()
        self.held_input = bytearray()
        self.held_output = bytearray()
        self.held_prompt = bytearray()
        self.prompt_waiting = False
        self.bundle_waiting = False
        self.bundle_phase = None
        self.bundle_lines = None
        self.suggestion_worker = None
        self.suggestion_future = None
        self.suggestion_request = None
        if autosuggest is True and self.bundle is None:
            self.notice("temporary editor bundle unavailable; continuing with destination GNU Readline")
        self.metrics = deque(maxlen=256)  # durations only; bounded, never transcripts

    def notice(self, text):
        if len(self.to_front) < LIMIT:
            self.to_front.extend(("\r\natuin-ssh: " + text + "\r\n").encode())

    def frame(self, event):
        fields = event.fields
        if (event.kind == "BUNDLE_REQUEST" and self.bundle and not self.handshake_seen
                and fields == (self.session,) and self.bundle_phase is None):
            self.bundle_waiting = True
            self.bundle_phase = "fence"
            self.bundle_deadline = time.monotonic() + 90
            self.held_input[:0] = self.to_backend
            self.to_backend.clear()
            self.to_backend.extend(f"!{self.nonce}:BUNDLE:FENCE\n".encode())
        elif (event.kind == "BUNDLE_HANDOVER" and self.bundle_phase == "fence"
              and len(fields) == 2 and fields[0] == self.session):
            try:
                if len(fields[1]) > 131072:
                    raise ValueError
                pending = bytes.fromhex(fields[1])
            except ValueError:
                self.abort_bundle()
                return
            self.held_input[:0] = pending
            self.bundle_phase = "transfer"
            self.bundle_lines = iter(self.bundle.lines(self.nonce))
        elif (event.kind == "BUNDLE_ABORT" and self.bundle_waiting
              and fields == (self.session,)):
            self.abort_bundle()
        elif event.kind == "ABORT" and len(fields) == 2 and fields[1] == self.session and fields[0].isdigit():
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
            if session != self.session or key not in {"up", "search", "suggest"}:
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
            if len(fields) not in {2, 3} or fields[0] != self.request[0]:
                return
            # Only the remote callback can assert ownership. It returns all
            # type-ahead preceding the fence in the SSH input byte stream.
            try:
                pending = (bytes.fromhex(fields[2]) if len(fields) == 3 and fields[1] == "hex"
                           else fields[1].encode("utf-8", "surrogateescape") if len(fields) == 2 else None)
                if pending is None or len(pending) > 65536:
                    raise ValueError
            except ValueError:
                self.send_response(fields[0], "cancel")
                return
            if self.request[1] == "suggest":
                self.open_suggestion(pending)
            else:
                self.open_widget(pending)
        elif (event.kind == "HELLO" and not self.handshake_seen and len(fields) == 5
              and fields[3] == self.session and fields[4] == "bash"):
            if self.bundle_waiting and self.bundle_phase not in {"await_hello", "aborting"}:
                # Releasing input while bundle bytes are in flight could put
                # those bytes in an editor. Close only our owned SSH instead.
                self.stopping = True
                return
            # A pre-existing hook emits DEGRADED before HELLO. Its actual
            # origin still belongs in provenance, without claiming enhancement.
            self.handshake_seen = True
            if self.bundle_waiting:
                self.bundle_waiting = False
                self.bundle_lines = None
                self.to_backend.extend(self.held_input)
                self.held_input.clear()
            if self.state == State.BOOTSTRAP:
                self.state = State.PROMPT
            if self.connection_registry:
                try:
                    self.connection_registry.origin(self.session, fields[0], fields[1])
                except Exception:
                    self.notice("connection provenance unavailable; native history remains usable")
        elif event.kind == "PROMPT" and not self.ui:
            self.state = State.PROMPT
            # A displayed prompt is also a cross-workstation visibility
            # boundary. Keep execution/transport independent from writes while
            # holding only the subsequent prompt bytes for a bounded interval.
            if self.outbox and not self.outbox.is_visible() and not self.prompt_waiting:
                self.prompt_waiting = True
                self.prompt_deadline = time.monotonic() + 0.5
        elif event.kind == "START":
            self.state = State.RUNNING
            if self.outbox:
                self.outbox_event(event)
        elif event.kind == "END":
            if self.outbox:
                self.outbox_event(event)
        elif event.kind == "DEGRADED":
            self.state = State.DEGRADED
            reason = DEGRADED_REASONS.get(fields[0]) if len(fields) == 1 else None
            self.notice(reason or "destination integration degraded; unsupported capture or history keys use ordinary Bash behavior")

    def abort_bundle(self):
        self.bundle_phase = "aborting"
        self.bundle_lines = None
        self.to_backend.clear()
        self.to_backend.extend((f"!{self.nonce}:BUNDLE:FENCE\n"
                                f"!{self.nonce}:BUNDLE:END:0:{'0' * 64}\n").encode())
        self.bundle_deadline = time.monotonic() + 90

    def open_suggestion(self, typeahead):
        req, _, line, point, _, _, host, user, cwd, session = self.request[:10]
        self.held_input[:0] = typeahead
        if self.held_input or not line or len(line.encode("utf-8", "surrogateescape")) > 4096:
            self.send_response(req, "cancel")
            return
        if int(point) != len(line.encode("utf-8", "surrogateescape")):
            self.send_response(req, "cancel")
            return
        if self.suggestion_future is not None and not self.suggestion_future.done():
            self.send_response(req, "cancel")
            return
        workspace = self.request[10] if len(self.request) == 11 else None
        if self.suggestion_worker is None:
            self.suggestion_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atuin-prefix")

        def query():
            from .context import origin_is_ambiguous
            root = str(state_root())
            if origin_is_ambiguous(root, session, host, user):
                return ""
            return self.native.suggest(Context(host, user, cwd, session, workspace=workspace), line)

        self.suggestion_future = self.suggestion_worker.submit(query)
        self.suggestion_request = req

    def poll_suggestion(self):
        future = self.suggestion_future
        if future is None or not future.done():
            return
        self.suggestion_future = None
        if (not self.request or self.request[0] != self.suggestion_request
                or self.request[1] != "suggest" or self.state != State.WAIT):
            return
        try:
            command = future.result() if not self.held_input else ""
        except Exception:
            command = ""
        self.send_response(self.request[0], "insert" if command else "cancel", command)

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

    def ordinary_output(self, data):
        target = self.held_output if self.ui else self.held_prompt if self.prompt_waiting else self.to_front
        target.extend(data)

    def release_prompt(self):
        self.to_front.extend(self.held_prompt)
        self.held_prompt.clear()
        self.prompt_waiting = False

    def ui_output(self, data):
        self.to_front.extend(data)
        controls = self.ui_control_tail + data
        for match in re.finditer(rb"\x1b\[\?([0-9;]+)([hl])", controls):
            if match.end() > len(self.ui_control_tail):
                for mode in match[1].split(b";"):
                    self.ui_modes[int(mode)] = match[2] == b"h"
        for match in re.finditer(rb"\x1b\[([><])[0-9;]*u", controls):
            if match.end() > len(self.ui_control_tail):
                self.ui_keyboard_depth = max(0, self.ui_keyboard_depth + (1 if match[1] == b">" else -1))
        self.ui_control_tail = controls[-64:]
        if not self.ui_ready:
            queries = self.ui_query_tail + data
            # Preserve fragmented queries, but count only newly completed
            # terminal requests. These replies must reach the native startup
            # negotiation while actual user keys remain queued until READY.
            for kind, pattern in (("cpr", rb"\x1b\[6n"), ("da", rb"\x1b\[(?:>|\?)?c"), ("keyboard", rb"\x1b\[\?u")):
                for match in re.finditer(pattern, queries):
                    if match.end() > len(self.ui_query_tail):
                        self.ui_expected[kind] += 1
            self.ui_query_tail = queries[-16:]
            self.route_startup_replies()

    def route_startup_replies(self):
        patterns = {"cpr": rb"\x1b\[\??[0-9]{1,5};[0-9]{1,5}R",
                    "da": rb"\x1b\[[?>]?[0-9;]{1,64}c",
                    "keyboard": rb"\x1b\[\?[0-9;]{1,64}u"}
        for kind, pattern in patterns.items():
            while self.ui_expected[kind]:
                match = re.search(pattern, self.ui_startup_input)
                if match is None:
                    break
                self.ui_negotiation.extend(match.group())
                del self.ui_startup_input[match.start():match.end()]
                self.ui_expected[kind] -= 1

    def open_widget(self, typeahead):
        req, key, line, point, mark, keymap, host, user, cwd, session = self.request[:10]
        workspace = self.request[10] if len(self.request) == 11 else None
        path = None
        ready_read = ready_write = None
        try:
            from .context import origin_is_ambiguous
            root = str(state_root())
            if origin_is_ambiguous(root, session, host, user):
                self.release_prompt()
                self.held_input.clear()
                self.notice("different SSH endpoints report this hostname/account; exact history scope is unresolved, captured events remain pending")
                self.send_response(req, "cancel")
                return
            if self.outbox:
                if not self.outbox.barrier(timeout=0.5):
                    self.notice("history writer is delayed; pending history may be absent")
            self.release_prompt()
            keymaps = {"vi-command": "vim-normal", "vi-insert": "vim-insert"}
            argv, env, path = self.native.prepare(Context(host, user, cwd, session, workspace=workspace), line,
                                                 up=key == "up", keymap=keymaps.get(keymap, "emacs"))
            ready_read, ready_write = pipe(nonblocking=True)
            os.set_inheritable(ready_write, True)
            env["ATUIN_SSH_READY_FD"] = str(ready_write)
            pid, fd = _spawn(argv, env, self.raw_attrs, self.size)
            os.close(ready_write)
            ready_write = None
            self.ui = (pid, fd, path)
            self.ready_fd = ready_read
            ready_read = None
            self.ready_buffer.clear()
            self.ui_ready = False
            self.ui_started = time.monotonic()
            self.ui_startup_input.clear()
            self.ui_negotiation.clear()
            self.ui_query_tail = b""
            self.ui_control_tail = b""
            self.ui_modes = {}
            self.ui_keyboard_depth = 0
            self.ui_expected = {"cpr": 0, "da": 0, "keyboard": 0}
            self.widget_cancelled = False
            self.to_ui.extend(typeahead)
            self.to_ui.extend(self.held_input)
            self.held_input.clear()
            self.state = State.UI
            self.metrics.append({"request_to_ui_ms": (time.monotonic() - self.request_time) * 1000})
        except Exception:
            # Input recovered for this widget must never become a command if
            # preparation fails, including an already-queued query + Enter.
            self.held_input.clear()
            for pipe_fd in (ready_read, ready_write):
                if pipe_fd is not None:
                    os.close(pipe_fd)
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
            self.ui_output(output)
        os.close(fd)
        self.ui = None
        if self.ready_fd is not None:
            os.close(self.ready_fd)
            self.ready_fd = None
        result = self.native.result(path, os.waitstatus_to_exitcode(status))
        # A signal bypasses native terminal destructors. Restore only modes
        # this UI actually enabled/left enabled; ordinary backend bytes remain
        # untouched. Readline performs its own redraw after the callback.
        for mode in (1000, 1002, 1003, 1006, 1015, 2004, 1049):
            if self.ui_modes.get(mode):
                self.to_front.extend(f"\x1b[?{mode}l".encode())
        if self.ui_modes.get(25) is False:
            self.to_front.extend(b"\x1b[?25h")
        if self.ui_keyboard_depth:
            self.to_front.extend(b"\x1b[<u" * self.ui_keyboard_depth)
        if os.waitstatus_to_exitcode(status):
            self.to_front.extend(b"\x1b[0m\r\x1b[K")
        self.send_response(self.request[0], "cancel" if self.widget_cancelled else result.action, result.command or "")
        self.metrics.append({"widget_duration_ms": (time.monotonic()-self.request_time)*1000})
        # Output received while UI active is replayed in original byte order.
        self.to_front.extend(self.held_output)
        self.held_output.clear()
        self.to_ui.clear()
        self.ui_startup_input.clear()
        self.ui_negotiation.clear()

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
                if self.bundle_waiting and time.monotonic() >= self.bundle_deadline:
                    if self.bundle_phase == "await_hello":
                        # END may already have returned tty ownership to the
                        # editor. Never inject a late cancellation command.
                        self.stopping = True
                        continue
                    self.abort_bundle()
                while self.bundle_lines is not None and len(self.to_backend) < 65536:
                    try:
                        line = next(self.bundle_lines)
                        self.to_backend.extend(line)
                        if line.startswith(f"!{self.nonce}:BUNDLE:END:".encode()):
                            self.bundle_lines = None
                            self.bundle_phase = "await_hello"
                    except StopIteration:
                        self.bundle_lines = None
                        self.bundle_phase = "await_hello"
                self.poll_suggestion()
                if self.prompt_waiting:
                    visible = self.outbox.is_visible()
                    if visible or time.monotonic() >= self.prompt_deadline:
                        self.release_prompt()
                        if not visible:
                            self.notice("history is pending; prompt resumed after bounded visibility wait")
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
                if len(self.to_backend)+len(self.held_input)+len(self.to_ui)+len(self.ui_startup_input) < LIMIT:
                    reads.append(self.front)
                if not backend_eof and (len(self.held_output) if self.ui else len(self.to_front)+len(self.held_prompt)) < LIMIT:
                    reads.append(backend_fd)
                if self.ui and len(self.to_front)<LIMIT:
                    reads.append(self.ui[1])
                if self.ready_fd is not None:
                    reads.append(self.ready_fd)
                if self.to_front:
                    writes.append(self.output)
                if self.to_backend and not backend_eof:
                    writes.append(backend_fd)
                if self.ui and (self.to_ui if self.ui_ready else self.ui_negotiation):
                    writes.append(self.ui[1])
                readable, writable, _ = select.select(reads, writes, [], 0.005 if self.prompt_waiting else 0.05)
                for fd in writable:
                    try:
                        _write(fd, self.to_front if fd == self.output else self.to_backend if fd == backend_fd else self.to_ui if self.ui_ready else self.ui_negotiation)
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
                            if self.ui_ready:
                                self.to_ui.extend(data)
                            else:
                                self.ui_startup_input.extend(data)
                                self.route_startup_replies()
                        elif self.bundle_waiting or self.state in {State.WAIT, State.RESTORE}:
                            self.held_input.extend(data)
                            if (not self.bundle_waiting and self.state == State.WAIT
                                    and self.request and self.request[1] == "suggest"
                                    and self.suggestion_future is not None
                                    and self.suggestion_request == self.request[0]):
                                # Typing takes priority over an idle suggestion.
                                # The native worker may finish in the background,
                                # but its old request can no longer edit a line.
                                self.send_response(self.request[0], "cancel")
                        else:
                            self.to_backend.extend(data)
                    elif fd == backend_fd:
                        if not data:
                            backend_eof = True
                        else:
                            for item in self.parser.feed(data):
                                if isinstance(item, bytes):
                                    self.ordinary_output(item)
                                else:
                                    self.frame(item)
                    elif fd == self.ready_fd:
                        self.ready_buffer.extend(data or b"")
                        if self.ready_buffer == b"READY\n":
                            self.ui_ready = True
                            os.close(self.ready_fd)
                            self.ready_fd = None
                            self.to_ui.extend(self.ui_startup_input)
                            self.ui_startup_input.clear()
                    elif data:
                        self.ui_output(data)
                if self.ui:
                    if not self.ui_ready and time.monotonic()-self.ui_started > 5:
                        self.widget_cancelled = True
                        self.notice("native UI readiness timed out; original editor restored")
                        try:
                            os.kill(self.ui[0], signal.SIGTERM)
                        except ProcessLookupError:
                            pass
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
                    self.ordinary_output(self.parser.finish())
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
                if backend_eof and backend_status is not None and not self.ui and not self.to_front and not self.held_prompt:
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
            if self.ready_fd is not None:
                os.close(self.ready_fd)
                self.ready_fd = None
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
            if self.suggestion_worker:
                self.suggestion_worker.shutdown(wait=False, cancel_futures=True)
