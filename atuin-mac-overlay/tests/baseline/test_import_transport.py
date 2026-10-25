"""Actual SSH import transport with an isolated HOME selected by a fixture key.

The account's ordinary profiles are never edited. Each test appends one owned
forced-command key, removes that exact line, and removes its own /tmp fixture.
"""
import base64
import hashlib
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from atuin_ssh.importing import fetch_history
import test_two_hop as interaction


@unittest.skipUnless(interaction.E2E, "disposable SSH fixture required")
class ImportTransportContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        interaction.TwoHopNativeWidget.setUpClass()
        cls.addClassCleanup(interaction.TwoHopNativeWidget.doClassCleanups)
        cls.base_config = interaction.TwoHopNativeWidget.config

    def ssh(self, command, *, data=None):
        return subprocess.run(["/usr/bin/ssh", "-F", str(self.base_config), self.target, command],
                              input=data, capture_output=True, check=True, timeout=15).stdout

    def write(self, path, content):
        self.ssh("base64 --decode > " + shlex.quote(path), data=base64.b64encode(content))

    def setUp(self):
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        self.target = user + "@" + os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        self.remote = self.ssh("mktemp -d /tmp/atuin-ssh-import-transport.XXXXXXXXXX").decode().strip()
        self.assertRegex(self.remote, r"^/tmp/atuin-ssh-import-transport\.[A-Za-z0-9]+$")
        self.addCleanup(self.ssh, "rm -rf -- " + shlex.quote(self.remote))
        local = tempfile.TemporaryDirectory(prefix="atuin-import-key-")
        self.addCleanup(local.cleanup)
        self.root = Path(local.name)
        self.identity = self.root / "id_ed25519"
        self.token = "atuin-import-fixture-" + uuid.uuid4().hex
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", self.token,
                        "-f", str(self.identity)], check=True, capture_output=True, timeout=10)
        forced = "env HOME=" + shlex.quote(self.remote) + ' /bin/sh -c "$SSH_ORIGINAL_COMMAND"'
        option = forced.replace("\\", "\\\\").replace('"', '\\"')
        key = 'command="' + option + '" ' + self.identity.with_suffix(".pub").read_text().strip()
        self.ssh("printf '%s\\n' " + shlex.quote(key) + ' >> "$HOME/.ssh/authorized_keys"')
        self.addCleanup(self.ssh, 'sed -i "/ ' + self.token + '$/d" "$HOME/.ssh/authorized_keys"')
        self.config = self.root / "config"
        self.config.write_text("\n".join(
            "  IdentityFile " + str(self.identity) if line.strip().startswith("IdentityFile ") else line
            for line in self.base_config.read_text().splitlines()) + "\n")
        self.histfile = self.remote + "/source-history"
        self.raw = ("#1700000100\nprintf 'λ界\\literal\tCR\rLF\nsecond'\n".encode()
                    + bytes(range(256)) + b"\nTRAILING\n\n")
        self.write(self.histfile, self.raw)
        self.profile()

    def profile(self, extra=""):
        self.write(self.remote + "/.bash_profile",
                   ("HISTFILE=" + shlex.quote(self.histfile) + "\n"
                    "printf '__IMPORT_PROFILE_OUTPUT__\\n'\n"
                    "stty opost onlcr\n" + extra + "\n").encode())

    def assert_source_unchanged(self):
        actual = self.ssh("cat -- " + shlex.quote(self.histfile))
        self.assertEqual(hashlib.sha256(actual).digest(), hashlib.sha256(self.raw).digest())

    def test_pty_fetch_preserves_custom_histfile_exact_bytes_and_source(self):
        source, content = fetch_history(self.target, ssh_options=["-F", str(self.config)])
        self.assertEqual(source["histfile"], self.histfile)
        self.assertEqual(source["user"], os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote"))
        self.assertEqual(content, self.raw)
        self.assert_source_unchanged()

    def test_byte_limit_failure_keeps_source_unchanged(self):
        with self.assertRaises(ValueError):
            fetch_history(self.target, max_bytes=len(self.raw) - 1, ssh_options=["-F", str(self.config)])
        self.assert_source_unchanged()

    def test_sigint_cancels_fetch_and_reaps_owned_ssh_child(self):
        ready = self.remote + "/blocked-ready"
        self.profile("printf ready > " + shlex.quote(ready) + "\nsleep 5")
        code = ("from atuin_ssh.importing import fetch_history; "
                "fetch_history(" + repr(self.target) + ", ssh_options=['-F', " + repr(str(self.config)) + "])")
        child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.stderr.close)
        # Remote stderr shares the PTY and is intentionally private to the
        # bounded reader. Observe a fixture-owned readiness file through an
        # independent SSH connection instead of depending on stream leakage.
        deadline = time.monotonic() + 5
        observed = b""
        while time.monotonic() < deadline:
            observed = self.ssh("test -f " + shlex.quote(ready) + " && printf READY || :")
            if observed == b"READY":
                break
            time.sleep(.05)
        self.assertEqual(observed, b"READY")
        children = Path(f"/proc/{child.pid}/task/{child.pid}/children").read_text().split()
        self.assertEqual(len(children), 1, "fetch must own exactly one SSH child")
        started = time.monotonic()
        child.send_signal(signal.SIGINT)
        child.communicate(timeout=5)
        self.assertNotEqual(child.returncode, 0)
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(Path("/proc", children[0]).exists(), "cancel left its SSH child running")
        self.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()
