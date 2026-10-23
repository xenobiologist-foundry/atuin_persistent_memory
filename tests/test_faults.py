"""Owned-process and in-band recovery faults through the real two-hop PTY."""
import subprocess
import unittest

import test_two_hop as interaction


@unittest.skipUnless(interaction.E2E, "disposable two-hop Compose fixture required")
class TerminalFailureRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        interaction.TwoHopNativeWidget.setUpClass()
        cls.addClassCleanup(interaction.TwoHopNativeWidget.doClassCleanups)

    def setUp(self):
        self.case = interaction.TwoHopNativeWidget("test_ctrl_r_inserts_into_same_remote_readline")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_native_ui_process_failure_restores_original_editor_and_keeps_ssh(self):
        self.case.client.send("printf '%s' ORIGINAL_BUFFER")
        self.case.client.send(b"\x01"+b"\x06"*7)
        before = self.case.snapshot()
        self.case.widget()
        # This command reaches only the named disposable hub, killing its owned
        # fixture UI child. The real SSH transport/controller must remain alive.
        subprocess.run(["/usr/bin/ssh", "-F", str(self.case.config), self.case.target,
                        "pkill -TERM -f '^/usr/local/bin/atuin-ssh-search search '"],
                       check=True, timeout=10, capture_output=True)
        returned = self.case.client.expect(interaction.PROMPT)
        self.assertIn(b"\x1b[?1000l", returned.string, "UI failure must restore native mouse mode")
        self.assertEqual(self.case.snapshot(), before)
        self.case.client.send(b"\x01\x0b")
        self.assertIn(b"__SSH_STILL_ALIVE__", self.case.command("printf '\\n__SSH_STILL_ALIVE__\\n'"))

    def test_corrupted_request_recovers_by_abort_without_executing_typeahead(self):
        # Rename only a trusted fixture function definition. Selected history
        # content never enters eval; the product does not use this test helper.
        self.case.command(r'''d=$(declare -f _as_emit); eval "${d/_as_emit /_e2e_original_emit }"; _as_emit() { if [[ $1 == REQUEST ]]; then printf '\033]777;atuin-ssh;1;%s;BAD;REQUEST;xx\007' "$_AS_NONCE"; else _e2e_original_emit "$@"; fi; }''')
        self.case.client.send("printf '%s' SAFE_ORIGINAL")
        before = self.case.snapshot()
        self.case.client.send(b"\x12printf SHOULD_NEVER_EXECUTE\r")
        # A lost request cannot establish UI ownership. The callback retains
        # raw ownership until its 30-second fence timeout and explicit ABORT.
        self.case.client.expect(interaction.PROMPT, timeout=40)
        self.assertEqual(self.case.snapshot(), before)
        self.case.client.send(b"\x01\x0b")
        output = self.case.command("printf '\\n__RECOVERED__\\n'")
        self.assertIn(b"__RECOVERED__", output)
        self.assertNotIn(b"\r\nSHOULD_NEVER_EXECUTE", self.case.client.transcript)


if __name__ == "__main__":
    unittest.main()
