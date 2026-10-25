"""Installed native UI scope contracts using real imported Bash history."""
from __future__ import annotations
import os
from pathlib import Path
import pwd
import shlex
import socket
import subprocess
import time
import unittest
import uuid
from unittest.mock import patch

import test_mac as mac
from atuin_ssh.importing import ImportLedger


class LocalHistoryScope(unittest.TestCase):
    setUp = mac.NativeMac.setUp
    start = mac.NativeMac.start
    command = mac.NativeMac.command
    rows = mac.NativeMac.rows

    def prepare_import(self):
        subprocess.run([str(mac.APP / "bin/atuin-layer"), "doctor"], env=self.env,
                       capture_output=True, check=True, timeout=10)
        self.native_env = dict(self.env, PATH=str(mac.APP / "bin") + os.pathsep + self.env["PATH"],
            ATUIN_HOME=str(self.state / "atuin"), ATUIN_CONFIG_DIR=str(self.state / "config"),
            ATUIN_DB_PATH=str(self.state / "atuin/history.db"),
            ATUIN_RECORD_STORE_PATH=str(self.state / "atuin/records.db"),
            ATUIN_KEY_PATH=str(self.state / "atuin/key"), ATUIN_META__DB_PATH=str(self.state / "atuin/meta.db"),
            ATUIN_SSH_STATE_DIR=str(self.state / "bridge"), ATUIN_AUTO_SYNC="false", ATUIN_UPDATE_CHECK="false",
            ATUIN_SESSION=uuid.uuid4().hex, ATUIN_HOST_NAME=socket.gethostname(),
            ATUIN_HOST_USER=pwd.getpwuid(os.getuid()).pw_name)
        self.token = "REMOTE_IMPORTED_SCOPE_"
        self.remote_command = "printf '%s\\n' '" + self.token + "é界'"
        source = dict(target="disposable-remote", host="scope-fixture-remote", user="remote-user",
                      histfile="/disposable/history")
        with patch.dict(os.environ, self.native_env):
            imported = ImportLedger(self.state / "bridge").import_bytes(source,
                ("#1700000000\n" + self.remote_command + "\n").encode())
        self.assertEqual(imported["imported"], 1)
        self.assertEqual(self.rows(self.token)[0][0], self.remote_command)

    def configure(self, key, value):
        result = subprocess.run([str(mac.APP / "bin/atuin"), "config", "set", key, value],
            env=self.native_env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, "native configuration update failed")

    def start_with_snapshot(self):
        self.start()
        self.snapshot_path = self.root / "authoritative scope snapshot"
        setup = ("scope_snapshot() { printf '%s\\0%s\\0' \"$BUFFER\" \"$POSTDISPLAY\" > "
                 + shlex.quote(str(self.snapshot_path))
                 + "; }; zle -N scope_snapshot; bindkey '^X^O' scope_snapshot")
        self.command(setup)

    def snapshot(self):
        self.snapshot_path.unlink(missing_ok=True)
        self.client.send(b"\x18\x0f")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.client.read(.03)
            if self.snapshot_path.exists():
                parts = self.snapshot_path.read_bytes().split(b"\0")
                if len(parts) == 3:
                    return parts[0].decode(), parts[1].decode()
        self.fail("ZLE did not deliver the authoritative editor state")

    def search_buffer(self, *, key=b"\x12", mode=b"GLOBAL"):
        self.client.buffer.clear()
        self.client.send(self.token.encode() + key)
        self.client.expect(mode, timeout=10)
        self.client.drain(.3)
        self.client.send(b"\t")
        self.client.expect(b"MAC-LOCAL> ", timeout=10)
        self.client.drain(.1)
        return self.snapshot()[0]

    def test_default_ctrl_r_inserts_exact_imported_remote_bash_without_scope_cycle(self):
        self.prepare_import()
        self.start_with_snapshot()
        self.assertEqual(self.search_buffer(), self.remote_command)
        self.assertEqual(len(self.rows(self.token)), 1, "inserting history must not execute it")

    def test_auto_shell_setting_hides_bash_in_local_global_search(self):
        self.prepare_import()
        self.configure("search.shells", "auto")
        self.start_with_snapshot()
        self.assertEqual(self.search_buffer(), self.token)
        self.assertEqual(len(self.rows(self.token)), 1)

    def test_custom_host_filter_is_honored_instead_of_forced_scope(self):
        self.prepare_import()
        self.configure("filter_mode", "host")
        self.start_with_snapshot()
        self.assertEqual(self.search_buffer(mode=b"HOST"), self.token)

    def test_up_remains_session_scoped_with_all_shells(self):
        self.prepare_import()
        self.start_with_snapshot()
        self.assertEqual(self.search_buffer(key=b"\x1b[A", mode=b"SESSION"), self.token)

    def test_remote_import_does_not_supply_local_inline_suggestions(self):
        self.prepare_import()
        self.start_with_snapshot()
        prefix = self.remote_command[:-4]
        self.client.send(prefix)
        self.client.drain(.7)
        self.assertEqual(self.snapshot(), (prefix, ""))
