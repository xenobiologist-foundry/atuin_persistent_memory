"""Independent behavioral PTY checks for terminal fidelity and foreground jobs."""

import os
import re
import shlex
from contextlib import closing
import sqlite3
import subprocess
import unittest
import uuid

import test_two_hop as interaction
from pty_client import PTYClient


@unittest.skipUnless(interaction.E2E, "disposable two-hop Compose fixture required")
class TerminalContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        interaction.TwoHopNativeWidget.setUpClass()
        cls.addClassCleanup(interaction.TwoHopNativeWidget.doClassCleanups)

    def setUp(self):
        self.case = interaction.TwoHopNativeWidget("test_ctrl_r_inserts_into_same_remote_readline")
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def test_output_matches_plain_openssh_for_all_byte_values_and_escapes(self):
        payload = (bytes(range(256))*4 + b"\x1b]0;ordinary-title\x07"
                   b"\x1b]133;A\x07\x1bPordinary-DCS\x1b\\"
                   b"\x1b]777;atuin-ssh;1;unnegotiated;1;HELLO;41\x07")
        octal = "".join(f"\\{value:03o}" for value in payload)
        begin = b"\x1e__BYTES_BEGIN__\x1f"
        end = b"\x1e__BYTES_END__\x1f"
        command = ("saved=$(stty -g); stty -opost; "
                   "printf '\\036__BYTES_BEGIN__\\037'; "
                   f"printf '{octal}'; "
                   "printf '\\036__BYTES_END__\\037'; stty \"$saved\"")
        destination = os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        plain = PTYClient(["/usr/bin/ssh", "-F", str(self.case.config), "-tt",
                           user+"@"+destination, command])
        self.addCleanup(plain.close)
        plain.expect(begin)
        result = plain.expect(end)
        observed_plain = result.string[:result.start()]
        self.case.client.send(command+"\n")
        self.case.client.expect(begin)
        result = self.case.client.expect(end)
        observed_enhanced = result.string[:result.start()]
        self.assertEqual(observed_plain, payload)
        self.assertEqual(observed_enhanced, observed_plain)

    def test_background_output_exceeding_buffer_is_complete_after_native_ui(self):
        count = 40_000
        flood = ("i=0; while ((i<40000)); do "
                   "printf '__FLOOD_%06d__abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz\\n' \"$i\"; "
                   "((i++)); done; printf '__FLOOD_DONE__\\n'; exit")
        command = ("(trap " + shlex.quote(flood) +
                   " USR1; while :; do sleep .02; done) & printf '\\n__FLOOD_PID__%s__\\n' \"$!\"")
        output = self.case.command(command)
        pid = int(re.search(rb"\r\n__FLOOD_PID__([0-9]+)__\r\n", output)[1])
        self.case.widget()
        destination = os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        # Start producing only AFTER actual native UI activation. A timed sleep
        # races a legitimately delayed prompt visibility barrier.
        subprocess.run(["/usr/bin/ssh", "-F", str(self.case.config), user+"@"+destination,
                        f"kill -USR1 -- {pid}"], check=True, timeout=10, capture_output=True)
        self.case.client.drain(1)
        # Backpressure must protect the native display, while the producing
        # process may block. No output is allowed to disappear on restoration.
        self.assertNotRegex(bytes(self.case.client.buffer), rb"__FLOOD_\d{6}__")
        self.case.client.send(b"\x1b")
        found = self.case.client.expect(b"__FLOOD_DONE__\r\n", timeout=60)
        occurrences = [int(value) for value in re.findall(rb"__FLOOD_(\d{6})__", found.string)]
        self.assertEqual(occurrences, list(range(count)))
        self.assertEqual(self.case.snapshot()[0], "")

    def test_ctrl_z_fg_ctrl_c_and_cat_eof(self):
        self.case.client.send("sleep 30\n")
        self.case.client.drain(.15)
        self.case.client.send(b"\x1a")
        self.case.client.expect(b"Stopped")
        self.case.client.expect(interaction.PROMPT)
        self.case.client.send("fg\n")
        self.case.client.drain(.15)
        self.case.client.send(b"\x03")
        self.case.client.expect(interaction.PROMPT)
        self.case.client.send("cat\n")
        self.case.client.drain(.1)
        self.case.client.send("__CAT_INPUT__\n")
        self.case.client.expect(b"__CAT_INPUT__\r\n")
        self.case.client.send(b"\x04")
        self.case.client.expect(interaction.PROMPT)
        self.assertEqual(self.case.snapshot()[0], "")

    def test_external_editor_binding_remains_bash_owned(self):
        self.case.command("export VISUAL='sed -i s/OLD/NEW/' EDITOR='sed -i s/OLD/NEW/'")
        self.case.client.send("printf '\\n__EDITOR__OLD\\n'")
        self.case.client.send(b"\x18\x05")
        self.case.client.expect(b"\r\n__EDITOR__NEW\r\n")
        self.case.client.expect(interaction.PROMPT)

    def test_destination_is_a_real_login_bash(self):
        output = self.case.command("shopt -q login_shell; printf '\\n__LOGIN__%s__\\n' \"$?\"")
        self.assertIn(b"__LOGIN__0__", output)

    def test_less_owns_search_and_navigation_then_returns_to_enhanced_prompt(self):
        self.case.client.send("LESSHISTFILE=- less -f -+F <(printf 'PAGER_FOREGROUND\\n'; printf '%s\\n' {1..200})\n")
        self.case.client.expect(b"PAGER_FOREGROUND\r\n")
        self.case.client.send(b"/150\r")
        self.case.client.drain(.15)
        self.case.client.send(b"\x1b[A\x12q")
        self.case.client.expect(interaction.PROMPT)
        self.assertNotRegex(bytes(self.case.client.transcript), interaction.NATIVE_UI)
        self.case.widget()
        self.case.client.send(b"\x1b")
        self.case.client.expect(interaction.PROMPT)

    def test_nano_owns_control_r_and_arrows(self):
        self.case.client.send("nano --ignorercfiles --view <(printf 'EDITOR_FOREGROUND\\n')\n")
        self.case.client.expect(b"GNU nano")
        self.case.client.send(b"\x1b[A\x12")
        self.case.client.drain(.15)
        self.case.client.send(b"\x03\x18")
        self.case.client.expect(interaction.PROMPT)
        self.assertNotRegex(bytes(self.case.client.transcript), interaction.NATIVE_UI)
        self.assertEqual(self.case.snapshot()[0], "")

    def test_top_owns_terminal_until_quit(self):
        self.case.client.send("top -d .2\n")
        self.case.client.expect(b"load average")
        self.case.client.send(b"\x1b[A\x12")
        self.case.client.drain(.15)
        self.case.client.send(b"q")
        self.case.client.expect(interaction.PROMPT)
        self.assertNotRegex(bytes(self.case.client.transcript), interaction.NATIVE_UI)
        self.assertEqual(self.case.snapshot()[0], "")

    def test_password_and_confirmation_input_are_not_capture_payloads(self):
        secret = "PASSWORD_INPUT_"+uuid.uuid4().hex
        # Split the printed readiness marker so command echo cannot satisfy it.
        self.case.client.send("printf '\\n__PASSWORD_%s__\\n' READY; IFS= read -rs secret; printf '\\n__PASSWORD_LENGTH__%s__\\n' \"${#secret}\"; unset secret\n")
        self.case.client.expect(b"\r\n__PASSWORD_READY__\r\n")
        self.case.client.send(secret+"\n")
        self.case.client.expect(f"\r\n__PASSWORD_LENGTH__{len(secret)}__\r\n".encode())
        self.case.client.expect(interaction.PROMPT)
        self.case.client.send("printf '\\n__CONFIRM_%s__\\n' READY; IFS= read -rn 1 answer; printf '\\n__ANSWER__%s__\\n' \"$answer\"\n")
        self.case.client.expect(b"\r\n__CONFIRM_READY__\r\n")
        self.case.client.send(b"y")
        self.case.client.expect(b"\r\n__ANSWER__y__\r\n")
        self.case.client.expect(interaction.PROMPT)
        self.assertNotIn(secret.encode(), self.case.client.transcript)
        self.assertNotRegex(bytes(self.case.client.transcript), interaction.NATIVE_UI)
        self.case.widget()
        self.case.client.send(b"\x1b")
        self.case.client.expect(interaction.PROMPT)
        with closing(sqlite3.connect("file:/test-state/atuin/data/history.db?mode=ro", uri=True)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM history WHERE command LIKE ?", ("%"+secret+"%",)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
