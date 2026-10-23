"""Actual OpenSSH compatibility against disposable, strictly verified hosts."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest
import uuid

from pty_client import PTYClient


E2E = os.environ.get("ATUIN_SSH_E2E") == "1"
NATIVE_UI = re.compile(rb"\x1b\[\?1000h.*?Atuin v18\.24\.1", re.S)


@unittest.skipUnless(E2E, "disposable SSH Compose fixture required (ATUIN_SSH_E2E=1)")
class OpenSSHCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.local = tempfile.TemporaryDirectory(prefix="atuin-ssh-compat-client-")
        cls.addClassCleanup(cls.local.cleanup)
        directory = Path(cls.local.name)
        keys = Path(os.environ.get("ATUIN_SSH_TEST_KEYS", "/test-keys"))
        known = directory / "known_hosts"
        hosts = []
        for name in ("hub", "destination"):
            key = (keys / f"{name}_host_ed25519.pub").read_text().split()
            hosts.append(f"{name} {key[0]} {key[1]}\n")
        known.write_text("".join(hosts))
        cls.config = directory / "config"
        cls.config.write_text(
            "Host *\n  BatchMode yes\n  StrictHostKeyChecking yes\n"
            f"  UserKnownHostsFile {known}\n"
            f"  IdentityFile {os.environ.get('ATUIN_SSH_TEST_KEY', '/test-keys/id_ed25519')}\n"
            "  IdentitiesOnly yes\n  ConnectTimeout 10\n",
        )
        cls.hub = (os.environ.get("ATUIN_SSH_TEST_HUB_USER", "hubuser") + "@" +
                   os.environ.get("ATUIN_SSH_TEST_HUB", "hub"))
        cls.destination = (os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote") + "@" +
                           os.environ.get("ATUIN_SSH_TEST_DEST", "destination"))

    def hub_run(self, argv, *, input=None, check=True):
        return subprocess.run(
            ["/usr/bin/ssh", "-F", str(self.config), self.hub, shlex.join(argv)],
            input=input, capture_output=True, timeout=20, check=check,
        )

    def setUp(self):
        self.remote = self.hub_run(["mktemp", "-d", "/tmp/atuin-ssh-compat.XXXXXXXX"]).stdout.decode().strip()
        self.assertRegex(self.remote, r"^/tmp/atuin-ssh-compat\.[A-Za-z0-9]+$")
        self.remote_config = self.remote + "/config"
        self.control = self.remote + "/control"
        self.addCleanup(self.cleanup_remote)
        text = (
            "Host contract-alias contract-command\n  HostName destination\n  User remote\n"
            "  HostKeyAlias destination\n"
            "Host contract-command\n  RemoteCommand printf '__SSH_REMOTE_COMMAND__\\n'\n"
            "Host *\n  BatchMode yes\n  StrictHostKeyChecking yes\n"
            "  UserKnownHostsFile /home/hubuser/.ssh/known_hosts\n"
            "  IdentityFile /home/hubuser/.ssh/id_ed25519\n"
            "  IdentitiesOnly yes\n  ConnectTimeout 10\n"
        )
        self.hub_run(["bash", "-c", "umask 077; cat > " + shlex.quote(self.remote_config)], input=text.encode())

    def cleanup_remote(self):
        # The socket and files belong solely to this test's mktemp directory.
        self.hub_run(["/usr/bin/ssh", "-S", self.control, "-O", "exit", self.destination], check=False)
        self.hub_run(["rm", "-f", "--", self.remote_config, self.control], check=False)
        self.hub_run(["rmdir", "--", self.remote], check=False)

    def open_hub(self):
        client = PTYClient(["/usr/bin/ssh", "-F", str(self.config), "-tt", self.hub])
        self.addCleanup(client.close)
        token = uuid.uuid4().hex
        client.send("PS1='__SSH_HUB__> '; printf '\\n__SSH_READY_" + token + "__\\n'\n")
        client.expect(("\r\n__SSH_READY_" + token + "__\r\n").encode(), timeout=30)
        client.expect(b"__SSH_HUB__> ")
        client.buffer.clear()
        return client

    def enter_destination(self, client, args):
        client.send(shlex.join(["ssh", *args]) + "\n")
        client.drain(.35)
        token = uuid.uuid4().hex
        client.send("PS1='__SSH_DEST__> '; printf '\\n__SSH_DEST_" + token + "__\\n'\n")
        client.expect(("\r\n__SSH_DEST_" + token + "__\r\n").encode(), timeout=30)
        client.expect(b"__SSH_DEST__> ")
        client.send(b"\x12")
        client.expect(NATIVE_UI, timeout=20)
        client.send(b"\x1b")
        client.drain(.2)
        client.send("printf '\\n__SSH_AFTER_UI__\\n'\n")
        client.expect(b"\r\n__SSH_AFTER_UI__\r\n", timeout=20)
        client.send("exit\n")
        client.expect(b"__SSH_HUB__> ", timeout=20)

    def test_config_alias_keeps_real_native_enhancement(self):
        self.enter_destination(self.open_hub(), ["-F", self.remote_config, "contract-alias"])

    def test_explicit_command_retains_status_without_bootstrap(self):
        client = self.open_hub()
        client.send(shlex.join(["ssh", self.destination, "printf '\\n__SSH_COMMAND__\\n'; exit 23"]) + "\n")
        client.expect(b"\r\n__SSH_COMMAND__\r\n", timeout=20)
        client.expect(b"__SSH_HUB__> ")
        client.send("printf '\\n__SSH_STATUS__%s__\\n' \"$?\"\n")
        client.expect(b"\r\n__SSH_STATUS__23__\r\n")

    def test_configured_remote_command_is_preserved(self):
        client = self.open_hub()
        client.send(shlex.join(["ssh", "-F", self.remote_config, "contract-command"]) + "\n")
        client.expect(b"__SSH_REMOTE_COMMAND__", timeout=20)
        client.expect(b"__SSH_HUB__> ")
        self.assertNotIn(b"Atuin v18.24.1", client.transcript)

    def test_proxyjump_through_hub_uses_strict_open_ssh(self):
        completed = subprocess.run(
            ["/usr/bin/ssh", "-F", str(self.config), "-J", self.hub,
             self.destination, "printf __SSH_PROXYJUMP__"],
            capture_output=True, timeout=25, check=True,
        )
        self.assertEqual(completed.stdout, b"__SSH_PROXYJUMP__")

    def test_forward_only_session_transports_real_ssh_banner(self):
        code = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()"
        port = int(self.hub_run(["python", "-c", code]).stdout)
        client = self.open_hub()
        client.send(shlex.join(["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-L",
                               f"127.0.0.1:{port}:destination:22", self.destination]) + "\n")
        probe = ("import socket; s=socket.create_connection(('127.0.0.1'," + str(port) +
                 "),timeout=2); print(s.recv(200).decode().strip()); s.close()")
        deadline = time.monotonic() + 12
        while True:
            result = self.hub_run(["python", "-c", probe], check=False)
            if result.returncode == 0:
                self.assertTrue(result.stdout.startswith(b"SSH-2.0-OpenSSH_"), result.stdout)
                break
            if time.monotonic() > deadline:
                self.fail("forward-only OpenSSH did not expose the destination SSH banner")
            client.drain(.1)
        client.send(b"\x03")
        client.drain(.2)
        client.send("printf '\\n__SSH_FORWARD_RETURNED__\\n'\n")
        client.expect(b"\r\n__SSH_FORWARD_RETURNED__\r\n")

    def test_shared_controlmaster_survives_enhanced_and_bypass_sessions(self):
        self.hub_run(["/usr/bin/ssh", "-M", "-S", self.control, "-fN", self.destination])
        self.hub_run(["/usr/bin/ssh", "-S", self.control, "-O", "check", self.destination])
        self.enter_destination(self.open_hub(), ["-S", self.control, "-o", "ControlMaster=no", self.destination])
        self.hub_run(["/usr/bin/ssh", "-S", self.control, "-O", "check", self.destination])
        result = self.hub_run(["atuin-ssh", "connect", "--", "-S", self.control,
                               self.destination, "printf __SSH_SHARED_BYPASS__"])
        self.assertEqual(result.stdout, b"__SSH_SHARED_BYPASS__")
        self.hub_run(["/usr/bin/ssh", "-S", self.control, "-O", "check", self.destination])
