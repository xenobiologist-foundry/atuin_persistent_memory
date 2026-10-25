"""Actual Bash 4.4 protocol/Readline checks in a Linux container.

Set ATUIN_SSH_TEST_BASH44 to an existing GNU Bash 4.4 executable. No binary is
downloaded or installed by these tests, and no destination host is contacted.
"""
from importlib.resources import files
import os
from pathlib import Path
import re
import shlex
import tempfile
import time
import unittest

from atuin_ssh.protocol import Frame, FrameParser, encode, response
from pty_client import PTYClient


BASH44 = os.environ.get("ATUIN_SSH_TEST_BASH44", "")
NONCE = "44" * 16
SESSION = "00000000000040008000000000000044"


class LegacyShell:
    def __init__(self, *, prompt="_as_probe_status=$?", date_output=None):
        self.temp = tempfile.TemporaryDirectory(prefix="atuin-ssh-bash44-")
        env = {"HOME": self.temp.name, "HISTFILE": str(Path(self.temp.name) / "history")}
        if date_output is not None:
            date = Path(self.temp.name) / "date"
            date.write_text("#!/bin/sh\nprintf '%s\\n' '" + date_output + "'\n")
            date.chmod(0o700)
            env["PATH"] = self.temp.name + ":" + os.environ["PATH"]
        payload = files("atuin_ssh").joinpath("bash/remote.bash").read_text()
        for old, new in (("@NONCE@", NONCE), ("@SESSION@", SESSION),
                         ("@BIND_CTRL_R@", "1"), ("@BIND_UP@", "1"),
                         ("@MIN_BASH_MAJOR@", "4")):
            payload = payload.replace(old, new)
        rc = "PS1='B44> '; unset PROMPT_COMMAND\n"
        rc += "PROMPT_COMMAND=" + shlex.quote(prompt) + "\n" + payload
        rc += r'''
_as_probe_snapshot() {
    _as_hex "$READLINE_LINE"
    printf '\nB44SNAP=%s:%s\n' "$_as_encoded" "$READLINE_POINT"
}
for _as_probe_map in emacs-standard vi-insert vi-command; do
    bind -m "$_as_probe_map" -x '"\C-x\C-d": _as_probe_snapshot'
done
unset _as_probe_map
'''
        self.rc_fd = os.memfd_create("atuin-ssh-bash44-rc", flags=0)
        os.write(self.rc_fd, rc.encode())
        os.lseek(self.rc_fd, 0, os.SEEK_SET)
        os.set_inheritable(self.rc_fd, True)
        self.client = PTYClient([BASH44, "--noprofile", "--rcfile", f"/proc/self/fd/{self.rc_fd}", "-i"], env=env)
        self.parser = FrameParser(NONCE)
        self.frames = []
        self.prompt(0)

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline or self.client.closed:
                raise AssertionError("Bash4.4 protocol timed out: " + repr(bytes(self.client.buffer[-2000:])))
            for item in self.parser.feed(self.client.read(.02)):
                if isinstance(item, Frame):
                    self.frames.append(item)

    def command(self, command):
        index = len(self.frames)
        self.client.send(command + "\r")
        self.wait(lambda: any(frame.kind == "END" for frame in self.frames[index:]))
        self.prompt(index)
        return self.frames[index:]

    def prompt(self, index):
        self.wait(lambda: any(frame.kind == "PROMPT" for frame in self.frames[index:]))
        prompt = next(frame for frame in self.frames[index:] if frame.kind == "PROMPT")
        self.client.expect(re.compile(re.escape(encode(NONCE, prompt)) + rb".*?B44> ", re.S))

    def widget(self, key, action, selected=""):
        index = len(self.frames)
        self.client.send(key)
        self.wait(lambda: any(frame.kind == "REQUEST" for frame in self.frames[index:]))
        request = next(frame for frame in self.frames[index:] if frame.kind == "REQUEST")
        ident = request.fields[0]
        self.client.send(f"!{NONCE}:{ident}:FENCE\n")
        self.wait(lambda: any(frame.kind == "HANDOVER" and frame.fields[0] == ident for frame in self.frames[index:]))
        self.client.send(response(NONCE, ident, action, selected))
        self.wait(lambda: any(frame.kind == "RELEASE" and frame.fields[0] == ident for frame in self.frames[index:]))
        return request, index

    def snapshot(self):
        self.client.send(b"\x18\x04")
        found = self.client.expect(re.compile(rb"B44SNAP=([0-9a-f]*):([0-9]+)\r?\n"))
        return bytes.fromhex(found[1].decode()).decode(), int(found[2])

    def close(self):
        self.client.close()
        os.close(self.rc_fd)
        self.temp.cleanup()


@unittest.skipUnless(BASH44 and Path(BASH44).is_file(), "actual optional Bash4.4 binary required")
class LegacyBashContracts(unittest.TestCase):
    def test_actual_legacy_capture_clock_status_and_scalar_prompt_hook(self):
        shell = LegacyShell()
        try:
            frames = shell.command("(exit 17)")
            start = next(frame for frame in frames if frame.kind == "START")
            end = next(frame for frame in frames if frame.kind == "END")
            self.assertEqual(start.fields[1], "(exit 17)")
            self.assertRegex(start.fields[-1], r"^[0-9]+\.[0-9]{9}$")
            self.assertRegex(end.fields[-1], r"^[0-9]+\.[0-9]{9}$")
            self.assertGreaterEqual(float(end.fields[-1]), float(start.fields[-1]))
            self.assertEqual(end.fields[1], "17")
            shell.command("printf 'PC_STATUS=%s\\n' \"$_as_probe_status\"")
            self.assertIn(b"PC_STATUS=17\r\n", shell.client.transcript)
        finally:
            shell.close()

    def test_actual_legacy_readline_cancel_insert_accept_and_up(self):
        shell = LegacyShell()
        try:
            shell.command(r'''bind '"\C-]": set-mark' ''')
            original = "echo λORIGINAL"
            shell.client.send(original.encode() + b"\x1d" + b"\x1b[D" * 4)
            shell.client.send(b"\x18\x18")
            original_mark_point = shell.snapshot()[1]
            shell.client.send(b"\x18\x18")
            request, _ = shell.widget(b"\x12", "cancel")
            self.assertEqual(request.fields[2], original)
            self.assertEqual(request.fields[5], "emacs-standard")
            self.assertEqual(shell.snapshot(), (original, int(request.fields[3])))
            # 4.4 exposes no READLINE_MARK variable. Exercise the real mark
            # through Readline's exchange-point-and-mark action instead.
            shell.client.send(b"\x18\x18")
            self.assertEqual(shell.snapshot(), (original, original_mark_point))
            shell.client.send(b"\x18\x18")
            selected = "printf 'λ_INSERT_ONLY\\n'"
            up, _ = shell.widget(b"\x1b[A", "insert", selected)
            self.assertEqual(up.fields[1:2], ("up",))
            self.assertEqual(up.fields[5], "emacs-standard")
            inserted = shell.snapshot()
            shell.client.send(b"\x05")
            self.assertEqual(shell.snapshot(), inserted)
            self.assertEqual(inserted[0], selected)
            accepted = "printf 'B44_NATIVE_ACCEPT\\n'"
            _, index = shell.widget(b"\x12", "accept", accepted)
            shell.wait(lambda: any(frame.kind == "END" for frame in shell.frames[index:]))
            start = next(frame for frame in shell.frames[index:] if frame.kind == "START")
            end = next(frame for frame in shell.frames[index:] if frame.kind == "END")
            self.assertEqual(start.fields[1], accepted)
            self.assertEqual(end.fields[1], "0")
            shell.client.expect(b"B44_NATIVE_ACCEPT\r\n")
        finally:
            shell.close()

    def test_actual_legacy_vi_maps_cancel_and_accept_in_the_same_editor(self):
        for mode, key in (("vi-insert", b"\x12"), ("vi-command", b"/")):
            with self.subTest(mode=mode):
                shell = LegacyShell()
                try:
                    shell.command("set -o vi")
                    shell.client.send("printf 'λ_VI_ORIGINAL'")
                    if mode == "vi-command":
                        shell.client.send(b"\x1b")
                        shell.client.drain(.1)
                    before = shell.snapshot()
                    request, _ = shell.widget(key, "cancel")
                    self.assertEqual(request.fields[5], mode)
                    self.assertEqual(shell.snapshot(), before)
                    accepted = "printf 'B44_VI_ACCEPT\\n'"
                    _, index = shell.widget(key, "accept", accepted)
                    shell.wait(lambda: any(frame.kind == "END" for frame in shell.frames[index:]))
                    start = next(frame for frame in shell.frames[index:] if frame.kind == "START")
                    end = next(frame for frame in shell.frames[index:] if frame.kind == "END")
                    self.assertEqual(start.fields[1], accepted)
                    self.assertEqual(end.fields[1], "0")
                    shell.client.expect(b"B44_VI_ACCEPT\r\n")
                finally:
                    shell.close()

    def test_legacy_nanosecond_component_is_left_padded_without_decimal_rescaling(self):
        shell = LegacyShell(date_output="1700000000 20554454")
        try:
            frames = shell.command("printf 'PADDED_CLOCK\\n'")
            times = [frame.fields[-1] for frame in frames if frame.kind in {"START", "END"}]
            self.assertEqual(times, ["1700000000.020554454", "1700000000.020554454"])
        finally:
            shell.close()


if __name__ == "__main__":
    unittest.main()
