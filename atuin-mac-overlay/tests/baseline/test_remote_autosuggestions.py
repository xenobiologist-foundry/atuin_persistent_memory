"""Temporary destination ble.sh, real hub-native history, and two SSH hops.

The destination runs no Python or Atuin. Only test-owned /tmp fixtures and an
editor snapshot widget are added by these tests; ordinary profiles are hashed.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import unittest
import uuid

import test_ssh_integration as ssh_fixture
import test_two_hop as flow


PROMPT = b"__REMOTE_BLE__> "
RENDERED_PROMPT = re.compile(rb"(?:\x1b\[2K|\r\n)__REMOTE_BLE__> ")


@unittest.skipUnless(flow.E2E, "disposable SSH fixture required")
class RemoteAutosuggestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ssh_fixture.OpenSSHCompatibility.setUpClass()
        cls.addClassCleanup(ssh_fixture.OpenSSHCompatibility.doClassCleanups)
        cls.config = ssh_fixture.OpenSSHCompatibility.config
        cls.hub = ssh_fixture.OpenSSHCompatibility.hub
        cls.destination = ssh_fixture.OpenSSHCompatibility.destination

    def ssh_run(self, target, arguments, *, check=True):
        return subprocess.run(["/usr/bin/ssh", "-F", str(self.config), target,
                               shlex.join(arguments)], capture_output=True,
                              check=check, timeout=20)

    def hub_run(self, arguments, *, check=True):
        return self.ssh_run(self.hub, arguments, check=check)

    def remote_run(self, arguments, *, check=True):
        return self.ssh_run(self.destination, arguments, check=check)

    def home_inventory(self):
        command = ('find "$HOME" -maxdepth 4 -type f ! -name .bash_history '
                   '-print0 | sort -z | xargs -0 -r sha256sum')
        return self.remote_run(["sh", "-c", command]).stdout

    def setUp(self):
        self.user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        self.host = os.environ.get("ATUIN_SSH_TEST_DEST_HOSTNAME", "destination")
        self.before_inventory = self.home_inventory()
        self.snapshot_path = self.remote_run(
            ["mktemp", "/tmp/atuin-remote-editor-test.XXXXXXXX"]).stdout.decode().strip()
        self.assertRegex(self.snapshot_path, r"^/tmp/atuin-remote-editor-test\.[A-Za-z0-9]+$")
        self.addCleanup(self.remote_run, ["rm", "-f", "--", self.snapshot_path])
        self.client = ssh_fixture.OpenSSHCompatibility.open_hub(self)
        self.connected = False
        self.addCleanup(self.close_destination)
        arguments = ["atuin-ssh", "connect", "--autosuggest"]
        if os.environ.get("ATUIN_SSH_TEST_FORCE_BASH") == "1":
            arguments.append("--bash")
        self.client.send(shlex.join([*arguments, "--", self.destination]) + "\n")
        initial_prompt = re.compile(re.escape((self.user + "@" + self.host).encode())
                                    + rb"(?:\x1b\[[0-9;]*m)*:[^\r\n]*\$ ")
        self.client.expect(initial_prompt, timeout=45)
        self.connected = True
        # This widget reads the active editor's own state, independently of
        # terminal rendering and of the bridge's protocol implementation.
        setup = (
            "ble/widget/atuin-ssh-test-snapshot() { local h; "
            "h=$(printf %s \"$_ble_edit_str\" | od -An -v -tx1 | tr -d ' \\n'); "
            "printf '%s:%s:%s:%s:%s:%s\\n' \"$((++_as_test_serial))\" \"$h\" "
            '"$_ble_edit_ind" "$_ble_edit_mark" "${_ble_edit_mark_active-}" '
            '"$_ble_decode_keymap" > ' + shlex.quote(self.snapshot_path) + "; }; "
            "ble-bind -m emacs -f 'C-x C-o' atuin-ssh-test-snapshot; "
            "PS1='__REMOTE_BLE__> '; "
            "printf '\\n__REMOTE_BLE_READY__%s|%s|%s|%s|%s|%s|%s__\\n' "
            '"${BLE_ATTACHED-unset}" "${BLE_VERSION-unset}" "$_AS_HOST" "$_AS_USER" '
            '"$_AS_SESSION" "${_AS_BLE_SESSION_DIR-unset}" "${_ble_base-unset}"'
        )
        self.client.send(setup + "\n")
        ready = self.client.expect(re.compile(rb"\r\n__REMOTE_BLE_READY__([^\r\n]*)__\r\n"), timeout=30)
        fields = ready[1].decode().split("|")
        self.assertEqual(len(fields), 7)
        self.assertEqual(fields[0], "1", "temporary destination editor must be attached")
        self.assertIn("d81fd54", fields[1])
        self.assertEqual(fields[2:4], [self.host, self.user])
        self.session, self.session_directory, self.bundle_directory = fields[4:]
        self.assertTrue(self.session)
        self.assertNotEqual(self.session_directory, "unset")
        self.assertTrue(self.bundle_directory.startswith(self.session_directory + "/")
                        or self.bundle_directory == self.session_directory)
        self.wait_prompt()
        self.serial = 0

    def wait_prompt(self):
        self.client.expect(RENDERED_PROMPT, timeout=20)

    def close_destination(self):
        if not self.connected:
            return
        # Failure cleanup is best effort; assertions use a normal explicit exit
        # in the cleanup contract below. The workstation PTY is also reaped.
        self.client.send(b"\x03")
        self.client.drain(.15)
        self.client.send(b"\x01\x0bexit\r")
        self.client.drain(.3)
        self.connected = False

    def snapshot(self):
        self.serial += 1
        self.client.send(b"\x18\x0f")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.remote_run(["cat", "--", self.snapshot_path]).stdout.decode().rstrip("\n")
            fields = result.split(":")
            if len(fields) == 6 and fields[0] == str(self.serial):
                self.assertEqual(self.remote_run(["test", "-d", self.session_directory], check=False).returncode,
                                 0, "a command substitution in the snapshot must not remove the parent session bundle")
                return (bytes.fromhex(fields[1]).decode(), int(fields[2]),
                        int(fields[3]), fields[4], fields[5])
            self.client.read(.03)
        self.fail("authoritative destination editor snapshot was not delivered: " + repr(result))

    def type_text(self, value):
        # Ordinary typing, rather than a pasted batch, triggers ble.sh's idle
        # completion scheduling. No source is invoked directly by the test.
        for character in value:
            self.client.send(character)
            self.client.drain(.03)

    def clear_line(self):
        self.client.send(b"\x01\x0b")

    def seed(self, command, *, user=None, host=None, session=None):
        identifier = uuid.uuid4().hex
        event = {"id": identifier, "host": host or self.host, "user": user or self.user,
                 "cwd": "/home/" + self.user, "session": session or self.session,
                 "shell": "bash", "command": command, "timestamp_ns": str(time.time_ns()),
                 "status": 0, "duration_ns": 1_000_000}
        probe = ("import json,sys; from atuin_ssh.atuin import NativeAtuin; "
                 "print(json.dumps(NativeAtuin().native('write',json.loads(sys.argv[1]))))")
        result = json.loads(self.hub_run(["python", "-c", probe, json.dumps(event)]).stdout)
        self.assertEqual(result["state"], "committed")
        return identifier

    def query(self, statement, parameters=()):
        probe = ("from contextlib import closing; import json,sqlite3,sys; "
                 "db=sqlite3.connect('file:/state/atuin/data/history.db?mode=ro',uri=True); "
                 "print(json.dumps(db.execute(sys.argv[1],json.loads(sys.argv[2])).fetchall())); db.close()")
        return json.loads(self.hub_run(["python", "-c", probe, statement,
                                       json.dumps(parameters)]).stdout)

    def rows(self, command):
        return self.query("SELECT hostname,cwd,exit,session FROM history WHERE command=? AND deleted_at IS NULL",
                          (command,))

    def wait_occurrence(self, command, status):
        deadline = time.monotonic() + 8
        rows = self.rows(command)
        while len(rows) != 2 and time.monotonic() < deadline:
            self.client.read(.05)
            rows = self.rows(command)
        self.assertEqual(len(rows), 2, "one seed plus exactly one accepted execution is required")
        self.assertIn([self.host + ":" + self.user, "/home/" + self.user, status, self.session], rows)
        self.assertEqual(self.remote_run(["test", "-d", self.session_directory], check=False).returncode,
                         0, "an executed subshell must not remove the parent session bundle")

    def test_account_history_ghost_right_accept_and_enter_capture(self):
        group = "REMOTE_GHOST_" + uuid.uuid4().hex + "_"
        prefix = "echo " + group
        command = prefix + "THIS_ACCOUNT"
        self.seed(command)
        # Newer rows from the same hostname's other account must not win.
        self.seed(prefix + "OTHER_ACCOUNT", user="other-fixture-account")
        self.client.buffer.clear()
        self.type_text(prefix)
        self.client.expect(b"THIS_ACCOUNT", timeout=15)
        self.assertNotIn(b"OTHER_ACCOUNT", self.client.buffer)
        self.assertEqual(len(self.rows(command)), 1)
        self.client.send(b"\x1b[C")
        self.assertEqual(self.snapshot()[0], command)
        self.assertEqual(len(self.rows(command)), 1, "Right Arrow must not execute a suggestion")
        self.client.send(b"\r")
        self.client.expect((group + "THIS_ACCOUNT\r\n").encode(), timeout=15)
        self.wait_prompt()
        self.wait_occurrence(command, 0)

    def test_tab_completion_uses_a_directory_present_only_on_destination(self):
        directory = self.remote_run(["mktemp", "-d", "/tmp/atuin-remote-completion.XXXXXXXX"]).stdout.decode().strip()
        completion_token = uuid.uuid4().hex
        child = directory + "/only-on-destination-" + completion_token
        self.remote_run(["mkdir", "--", child])
        self.addCleanup(self.remote_run, ["rmdir", "--", child, directory])
        self.assertNotEqual(self.hub_run(["test", "-e", child], check=False).returncode, 0)
        self.client.send("cd " + directory + "/only-on-dest")
        self.client.send(b"\t")
        # Completion runs asynchronously. A snapshot key sent immediately can
        # cancel that pending editor action before its result is inserted.
        self.client.expect(completion_token.encode(), timeout=10)
        self.assertIn(self.snapshot()[0], ("cd " + child + "/", "cd " + child + "/ "))
        self.clear_line()

    def test_native_ctrl_r_inserts_and_up_accepts_same_session_selection(self):
        token = "REMOTE_NATIVE_" + uuid.uuid4().hex
        command = f"printf '\\n%s\\n' {token}; (exit 17)"
        self.seed(command)
        self.client.send(token + "\x12")
        self.client.expect(flow.NATIVE_UI, timeout=20)
        self.client.expect(b"ACCOUNT")
        self.client.send(b"\t")
        self.wait_prompt()
        self.assertEqual(self.snapshot()[0], command)
        self.assertEqual(len(self.rows(command)), 1)
        self.clear_line()
        self.client.send(b"\x1b[A")
        self.client.expect(flow.NATIVE_UI, timeout=20)
        self.client.expect(b"SESSION")
        self.client.send(b"\r")
        self.client.expect((token + "\r\n").encode(), timeout=15)
        self.wait_prompt()
        self.wait_occurrence(command, 17)

    def test_native_cancel_preserves_unicode_buffer_cursor_mark_and_keymap(self):
        self.client.send("printf '%s\\n' 'AAé界ZZ'")
        self.client.send(b"\x01" + b"\x06" * 8 + b"\x00" + b"\x06" * 3)
        before = self.snapshot()
        self.client.send(b"\x12")
        self.client.expect(flow.NATIVE_UI, timeout=20)
        self.client.send(b"\x1b")
        self.wait_prompt()
        self.assertEqual(self.snapshot(), before)
        self.clear_line()

    def test_activation_query_and_enter_in_one_write_remain_native_ui_input(self):
        token = "REMOTE_BURST_" + uuid.uuid4().hex
        command = f"printf '\\n%s\\n' {token}; (exit 23)"
        self.seed(command)
        self.seed("echo REMOTE_DISTRACTOR_" + uuid.uuid4().hex)
        self.client.send(b"\x12" + token.encode() + b"\r")
        self.client.expect(flow.NATIVE_UI, timeout=20)
        self.client.expect((token + "\r\n").encode(), timeout=15)
        self.wait_prompt()
        self.wait_occurrence(command, 23)

    def test_foreground_read_e_and_password_keep_their_own_input(self):
        typed = "READ_INPUT_" + uuid.uuid4().hex
        command = ("IFS= read -e -r -p '__REMOTE_READ_E__> ' value; "
                   "printf '\\n__REMOTE_READ_VALUE__%s__\\n' \"$value\"")
        self.client.send(command + "\n")
        self.client.expect(re.compile(rb"(?:\r\n|\x1b\[2K)__REMOTE_READ_E__> "), timeout=15)
        start = len(self.client.transcript)
        self.client.send(b"\x12\x07\x1b[A\x07\x01\x0b" + typed.encode() + b"\r")
        self.client.expect(("__REMOTE_READ_VALUE__" + typed + "__\r\n").encode(), timeout=15)
        self.wait_prompt()
        self.assertNotRegex(bytes(self.client.transcript[start:]), flow.NATIVE_UI)
        self.assertNotIn(b"\x1b]777;atuin-ssh;1;", self.client.transcript[start:],
                         "nested foreground input must not leak stale bridge protocol frames")
        secret = "PASSWORD_INPUT_" + uuid.uuid4().hex
        self.client.send("printf '\\n__REMOTE_PASSWORD_%s__\\n' READY; IFS= read -rs secret; "
                         "printf '\\n__REMOTE_PASSWORD_LENGTH__%s__\\n' \"${#secret}\"; unset secret\n")
        self.client.expect(b"__REMOTE_PASSWORD_READY__\r\n")
        self.client.send(secret + "\n")
        self.client.expect(f"__REMOTE_PASSWORD_LENGTH__{len(secret)}__\r\n".encode())
        self.wait_prompt()
        self.assertNotIn(secret.encode(), self.client.transcript)
        self.assertEqual(self.query("SELECT count(*) FROM history WHERE command LIKE ? OR command LIKE ?",
                                    ("%" + typed + "%", "%" + secret + "%")), [[0]])

    def test_graceful_exit_removes_session_bundle_and_preserves_destination_files(self):
        self.remote_run(["test", "-d", self.session_directory])
        self.remote_run(["test", "-d", self.bundle_directory])
        self.client.send("exit\n")
        self.client.expect(b"\x1b[2K__SSH_HUB__> ", timeout=20)
        self.connected = False
        deadline = time.monotonic() + 5
        exists = self.remote_run(["test", "-e", self.session_directory], check=False).returncode == 0
        while exists and time.monotonic() < deadline:
            self.client.read(.05)
            exists = self.remote_run(["test", "-e", self.session_directory], check=False).returncode == 0
        self.assertFalse(exists, "temporary editor/session files must be removed after logout")
        self.assertEqual(self.home_inventory(), self.before_inventory)


if __name__ == "__main__":
    unittest.main()
