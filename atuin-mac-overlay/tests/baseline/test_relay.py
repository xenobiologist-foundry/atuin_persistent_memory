"""Relay handshake/diagnostic contracts, without spawning SSH or native UI."""
import unittest

from atuin_ssh.protocol import Frame, encode
from atuin_ssh.relay import Relay, State


class RecordingRegistry:
    def __init__(self):
        self.origins = []

    def origin(self, session, host, account):
        self.origins.append((session, host, account))


class RelayHandshakeContracts(unittest.TestCase):
    def setUp(self):
        self.relay = Relay([])
        self.registry = RecordingRegistry()
        self.relay.connection_registry = self.registry

    def receive(self, kind, sequence, fields):
        # Exercise actual wire decoding as well as the frame dispatcher. In
        # particular, a hex-encoded unknown diagnostic remains untrusted text.
        events = self.relay.parser.feed(encode(self.relay.nonce, Frame(kind, sequence, fields)))
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], Frame)
        self.relay.frame(events[0])

    def hello(self, sequence=1, *, session=None, host="actual-host", account="alice"):
        self.receive("HELLO", sequence,
                     (host, account, "/remote/work", self.relay.session if session is None else session, "bash"))

    def test_degraded_before_hello_records_origin_without_erasing_degradation(self):
        self.receive("DEGRADED", 1,
                     ("Existing DEBUG trap/functrace: capture and native hub keys unavailable for this shell.",))
        self.assertEqual(self.relay.state, State.DEGRADED)
        self.hello(sequence=2)
        self.assertEqual(self.registry.origins, [(self.relay.session, "actual-host", "alice")])
        self.assertEqual(self.relay.state, State.DEGRADED)

    def test_invalid_hello_does_not_complete_handshake_or_prevent_valid_one(self):
        invalid = ((), ("host",),
                   ("host", "alice", "/remote", self.relay.session),
                   ("host", "alice", "/remote", "other-session", "bash"),
                   ("host", "alice", "/remote", self.relay.session, "zsh"),
                   ("host", "alice", "/remote", self.relay.session, "bash", "extra"))
        for sequence, fields in enumerate(invalid, 1):
            with self.subTest(fields=fields):
                self.receive("HELLO", sequence, fields)
                self.assertEqual(self.registry.origins, [])
                self.assertEqual(self.relay.state, State.BOOTSTRAP)
        self.hello(sequence=len(invalid) + 1)
        self.assertEqual(self.registry.origins, [(self.relay.session, "actual-host", "alice")])
        self.assertEqual(self.relay.state, State.PROMPT)

    def test_repeated_hello_cannot_rewrite_origin_or_reset_state(self):
        self.hello()
        self.relay.state = State.RUNNING
        self.hello(sequence=2, host="replacement-host", account="mallory")
        self.assertEqual(self.registry.origins, [(self.relay.session, "actual-host", "alice")])
        self.assertEqual(self.relay.state, State.RUNNING)

    def test_known_diagnostics_identify_specific_compatibility_reason(self):
        cases = (
            ("Accepted command exceeds capture bound.", b"256 KiB"),
            ("Accepted history expansion unavailable; command capture skipped.", b"Bash history expansion"),
            ("Complex HISTIGNORE: repeated-command capture unavailable; native history exclusions preserved.", b"complex HISTIGNORE"),
            ("DEBUG hook replaced: capture and native hub keys disabled for this shell.", b"DEBUG hook was replaced"),
            ("Existing DEBUG trap/functrace: capture and native hub keys unavailable for this shell.", b"existing DEBUG trap or functrace"),
        )
        for reason, explanation in cases:
            with self.subTest(reason=reason):
                self.relay = Relay([])
                self.receive("DEGRADED", 1, (reason,))
                message = bytes(self.relay.to_front)
                self.assertIn(explanation, message)
                self.assertNotIn(b"unsupported capture or history keys use ordinary Bash behavior", message)

    def test_unknown_diagnostic_does_not_print_remote_text_or_terminal_controls(self):
        untrusted = "REMOTE_SECRET_FIXTURE\r\n\x1b]0;injected-title\x07\x1b[2J"
        self.receive("DEGRADED", 1, (untrusted,))
        message = bytes(self.relay.to_front)
        self.assertIn(b"atuin-ssh:", message)
        self.assertNotIn(b"REMOTE_SECRET_FIXTURE", message)
        self.assertNotIn(b"injected-title", message)
        self.assertNotIn(b"\x1b", message)
        self.assertNotIn(b"\x07", message)
        self.assertEqual(self.relay.state, State.DEGRADED)


if __name__ == "__main__":
    unittest.main()
