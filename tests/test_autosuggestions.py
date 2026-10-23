"""Hub-only native Atuin history suggestions through a real workstation SSH."""
import re
import shlex
import subprocess
import time
import unittest
import uuid

import test_ssh_integration as ssh_fixture
import test_two_hop as flow


@unittest.skipUnless(flow.E2E, "disposable SSH fixture required")
class HubAutosuggestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ssh_fixture.OpenSSHCompatibility.setUpClass()
        cls.addClassCleanup(ssh_fixture.OpenSSHCompatibility.doClassCleanups)
        cls.config = ssh_fixture.OpenSSHCompatibility.config
        cls.hub = ssh_fixture.OpenSSHCompatibility.hub

    def hub_run(self, arguments, **kwargs):
        return subprocess.run(["/usr/bin/ssh", "-F", str(self.config), self.hub, shlex.join(arguments)],
                              capture_output=True, check=True, timeout=15, **kwargs)

    def setUp(self):
        self.client = ssh_fixture.OpenSSHCompatibility.open_hub(self)
        setup = ("printf '\\n__AUTOSUGGEST_READY__%s:%s:%s__\\n' \"${BLE_VERSION-unset}\" "
                 "\"$(type -t ble/complete/auto-complete/source:atuin-history)\" \"${ATUIN_SESSION-unset}\"")
        self.client.send(setup + "\n")
        ready = self.client.expect(re.compile(rb"\r\n__AUTOSUGGEST_READY__([^:\r]+):function:([^:\r]+)__\r\n"), timeout=20)
        self.assertIn(b"d81fd54", ready[1])
        self.assertNotEqual(ready[2], b"unset")
        self.client.expect(b"__SSH_HUB__> ")

    def seed(self):
        token = "SUGGEST_" + uuid.uuid4().hex
        command = f"echo {token}"
        prefix = ["env", "ATUIN_SESSION=autosuggestion-fixture"]
        identifier = self.hub_run([*prefix, "atuin", "history", "start", "--", command]).stdout.decode().strip()
        self.hub_run([*prefix, "atuin", "history", "end", "--exit", "0", "--duration", "1000000", "--", identifier])
        return token, command

    def native_count(self, command):
        code = ("import sqlite3,sys; "
                "db=sqlite3.connect('file:/state/atuin/data/history.db?mode=ro',uri=True); "
                "print(db.execute('select count(*) from history where command=?',(sys.argv[1],)).fetchone()[0])")
        return int(self.hub_run(["python", "-c", code, command]).stdout)

    def test_native_history_ghost_text_right_accepts_without_executing(self):
        token, command = self.seed()
        prefix, suffix = command[:-16], command[-16:]
        result = self.hub_run(["env", "ATUIN_SESSION=fixture", "ATUIN_QUERY=" + prefix, "atuin", "search", "--cmd-only", "--limit", "1", "--search-mode", "prefix"])
        self.assertEqual(result.stdout.decode().rstrip("\n"), command)
        self.client.buffer.clear()
        # Model typing: ble.sh deliberately suppresses idle completion for a
        # pasted input batch, which is a different editor action.
        for character in prefix:
            self.client.send(character)
            self.client.drain(.03)
        self.client.expect(suffix.encode(), timeout=10)
        self.assertEqual(self.native_count(command), 1, "ghost text must not execute a command")
        self.client.send(b"\x1b[C")
        self.assertEqual(self.native_count(command), 1, "accepting ghost text must not execute it")
        self.client.send(b"\r")
        self.client.expect((token + "\r\n").encode(), timeout=15)
        deadline = time.monotonic() + 5
        while self.native_count(command) != 2 and time.monotonic() < deadline:
            self.client.read(.05)
        self.assertEqual(self.native_count(command), 2, "Right Arrow must accept the exact full command")

    def test_native_history_search_still_opens_from_hub_editor(self):
        _, command = self.seed()
        self.client.send(b"\x12")
        self.client.expect(flow.NATIVE_UI, timeout=15)
        self.client.send(b"\x1b")
        self.client.expect(b"\x1b[2K__SSH_HUB__> ", timeout=15)
        self.client.send(b"\r")
        self.client.drain(.2)
        self.assertEqual(self.native_count(command), 1, "cancellation must not execute the selected history")
