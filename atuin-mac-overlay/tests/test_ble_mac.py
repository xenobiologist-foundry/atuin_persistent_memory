"""The seven pinned BLE contracts, driven by native Mac entry instead of a hub."""
from contextlib import closing
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import time
import unittest

import test_remote_autosuggestions as baseline
import test_mac as mac
APP = mac.APP


class NativeMacBLE(baseline.RemoteAutosuggestions):
    __unittest_skip__ = os.environ.get("ATUIN_LAYER_TEST_REMOTE") != "1"
    __unittest_skip_why__ = "pass --remote or --legacy for the owned destination"
    fixture = mac.RemoteMac.fixture
    start = mac.NativeMac.start
    remote_command = mac.RemoteMac.remote_command

    @classmethod
    def setUpClass(cls):
        pass

    def remote_run(self, arguments, *, check=True):
        return subprocess.run([*self.ssh, shlex.join(arguments)], capture_output=True, check=check, timeout=20)

    def hub_run(self, arguments, *, check=True):
        arguments = list(arguments)
        if arguments[0] == "python":
            arguments[0] = str(APP / "python/bin/python3")
            arguments[2] = "import sys;sys.path.insert(0," + repr(str(APP / "lib")) + ");" + arguments[2]
            arguments.insert(1, "-I")
        env = dict(self.env, PATH=str(APP / "bin")+os.pathsep+os.environ["PATH"],
                   ATUIN_HOME=str(self.state / "atuin"), ATUIN_CONFIG_DIR=str(self.state / "config"),
                   ATUIN_SSH_STATE_DIR=str(self.state / "bridge"), ATUIN_AUTO_SYNC="false", ATUIN_UPDATE_CHECK="false",
                   ATUIN_DB_PATH=str(self.state / "atuin/history.db"),
                   ATUIN_RECORD_STORE_PATH=str(self.state / "atuin/records.db"),
                   ATUIN_META__DB_PATH=str(self.state / "atuin/meta.db"), ATUIN_KEY_PATH=str(self.state / "atuin/key"))
        return subprocess.run(arguments, env=env, capture_output=True, check=check, timeout=20)

    def query(self, statement, parameters=()):
        with closing(sqlite3.connect(self.state / "atuin/history.db")) as database:
            return [list(row) for row in database.execute(statement, parameters)]

    def setUp(self):
        mac.NativeMac.setUp(self)
        self.fixture()
        self.user, self.host = "remote", "overlay-fixture"
        self.before_inventory = self.home_inventory()
        self.snapshot_path = self.remote_run(["mktemp", "/tmp/atuin-remote-editor-test.XXXXXXXX"]).stdout.decode().strip()
        self.addCleanup(self.remote_run, ["rm", "-f", "--", self.snapshot_path])
        self.connected = False
        mac.RemoteMac.connect(self)
        self.connected = True
        self.addCleanup(self.close_destination)
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
        self.assertEqual(fields[0], "1")
        self.assertIn("d81fd54", fields[1])
        self.assertEqual(fields[2:4], [self.host, self.user])
        self.session, self.session_directory, self.bundle_directory = fields[4:]
        self.wait_prompt()
        self.serial = 0

    def test_up_binding_recognizes_meta_notation_without_remote_utf8_locale(self):
        self.client.send("printf '\\nUP_FLAGS__%s|%s|%s__\\n' \"$_as_ble_bind_up_emacs\" \"$_as_ble_bind_up_vi\" \"$_as_ble_bind_up_normal\"\n")
        found = self.client.expect(re.compile(rb"\r\nUP_FLAGS__([^\r\n]+)__\r\n"))
        self.assertEqual(found[1], b"1|1|1")
        self.wait_prompt()

    def test_graceful_exit_removes_session_bundle_and_preserves_destination_files(self):
        self.remote_run(["test", "-d", self.session_directory])
        self.client.send("exit\n")
        self.client.expect(b"MAC-LOCAL> ", timeout=20)
        self.connected = False
        self.assertNotEqual(self.remote_run(["test", "-e", self.session_directory], check=False).returncode, 0)
        self.assertEqual(self.home_inventory(), self.before_inventory)
