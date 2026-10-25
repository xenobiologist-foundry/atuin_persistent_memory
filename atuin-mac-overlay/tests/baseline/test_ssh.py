"""Eligibility contracts: unsupported forms retain the original OpenSSH argv."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from atuin_ssh.ssh import enhanced_argv, plan_invocation


class SSHArguments(unittest.TestCase):
    def test_ordinary_login_options(self):
        for args in (
            ["host"], ["--", "host"], ["-vvCt", "host"],
            ["-p2222", "-J", "jump", "me@host"],
            ["-F", "path with spaces/config", "-o", "Compression=yes", "host"],
            ["-L8080:localhost:80", "host"], ["ssh://me@[::1]:2222"],
        ):
            with self.subTest(args=args):
                plan = plan_invocation(args, config_probe=False)
                self.assertTrue(plan.enhanced, plan.reason)
                self.assertEqual(plan.argv, tuple(args))
                self.assertEqual(enhanced_argv(plan, "bootstrap")[-1], "bootstrap")

    def test_special_operations_bypass_exactly(self):
        for args in (
            [], ["-N", "host"], ["-T", "host"], ["-n", "host"],
            ["-W", "host:22", "jump"], ["-s", "host", "sftp"],
            ["-Ocheck", "host"], ["-G", "host"], ["-Q", "cipher"], ["-V"],
            ["-fN", "host"], ["-vvvT", "host"], ["-t", "host", "top"],
            ["host", "printf", "two words"], ["host", "-p22"],
            ["--unknown", "host"], ["-j", "host"], ["-p"], ["--"],
        ):
            with self.subTest(args=args):
                plan = plan_invocation(args, config_probe=False)
                self.assertFalse(plan.enhanced)
                self.assertEqual(plan.argv, tuple(args))
                with self.assertRaises(ValueError):
                    enhanced_argv(plan, "bootstrap")

    def test_nonterminal_is_plain_ssh(self):
        self.assertFalse(plan_invocation(["host"], stdin_tty=False).enhanced)
        self.assertFalse(plan_invocation(["host"], stdout_tty=False).enhanced)

    @unittest.skipUnless(Path("/usr/bin/ssh").is_file(), "Linux OpenSSH required")
    def test_actual_openssh_config_remains_authoritative(self):
        # These are real OpenSSH evaluations, not a mirrored mock parser.
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.write_text(
                "Host ordinary\n  HostName 192.0.2.2\n  User sample\n  Port 2022\n"
                "Host command\n  RemoteCommand top\n"
                "Host no-tty\n  RequestTTY no\n"
                "Host null\n  StdinNull yes\n"
                "Host forward\n  SessionType none\n"
                "Host background\n  ForkAfterAuthentication yes\n",
                encoding="utf-8",
            )
            normal = plan_invocation(["-F", str(config), "ordinary"])
            self.assertTrue(normal.enhanced, normal.reason)
            self.assertEqual(normal.effective["hostname"], "192.0.2.2")
            self.assertEqual(normal.effective["user"], "sample")
            self.assertEqual(normal.effective["port"], "2022")
            for host in ("command", "no-tty", "null", "forward", "background"):
                with self.subTest(host=host):
                    self.assertFalse(plan_invocation(["-F", str(config), host]).enhanced)


if __name__ == "__main__":
    unittest.main()
