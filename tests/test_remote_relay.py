"""Ownership failures must not turn bundle or stale suggestion bytes into input."""
from concurrent.futures import Future
from types import SimpleNamespace
import unittest

from atuin_ssh.protocol import Frame, encode
from atuin_ssh.relay import Relay, State


class RemoteEditorOwnership(unittest.TestCase):
    def setUp(self):
        self.relay = Relay([], autosuggest=False)
        self.relay.bundle = SimpleNamespace(lines=lambda nonce: iter((b"bounded-data\n",)))
        self.sequence = 0

    def receive(self, kind, fields):
        self.sequence += 1
        frames = self.relay.parser.feed(encode(self.relay.nonce, Frame(kind, self.sequence, fields)))
        self.assertEqual(len(frames), 1)
        self.relay.frame(frames[0])

    def test_boot_fence_preserves_previously_sent_and_unsent_typeahead_in_order(self):
        relay = self.relay
        relay.to_backend.extend(b"unsent\x00\r")
        self.receive("BUNDLE_REQUEST", (relay.session,))
        self.assertEqual(relay.held_input, b"unsent\x00\r")
        self.assertEqual(relay.to_backend, f"!{relay.nonce}:BUNDLE:FENCE\n".encode())
        relay.held_input.extend(b"newer")
        self.receive("BUNDLE_HANDOVER", (relay.session, b"already-sent\xff".hex()))
        self.assertEqual(relay.held_input, b"already-sent\xffunsent\x00\rnewer")
        self.assertEqual(relay.bundle_phase, "transfer")

    def test_premature_editor_hello_cannot_release_input_over_bundle_bytes(self):
        relay = self.relay
        self.receive("BUNDLE_REQUEST", (relay.session,))
        relay.held_input.extend(b"USER_COMMAND\r")
        before = bytes(relay.to_backend)
        self.receive("HELLO", ("host", "user", "/", relay.session, "bash"))
        self.assertTrue(relay.stopping)
        self.assertFalse(relay.handshake_seen)
        self.assertEqual(relay.to_backend, before)
        self.assertEqual(relay.held_input, b"USER_COMMAND\r")

    def test_abort_drops_remaining_bundle_data_and_retains_user_input(self):
        relay = self.relay
        self.receive("BUNDLE_REQUEST", (relay.session,))
        self.receive("BUNDLE_HANDOVER", (relay.session, b"typed\r".hex()))
        relay.to_backend.extend(b"LATE_BUNDLE_DATA")
        self.receive("BUNDLE_ABORT", (relay.session,))
        self.assertIsNone(relay.bundle_lines)
        self.assertEqual(relay.bundle_phase, "aborting")
        self.assertNotIn(b"LATE_BUNDLE_DATA", relay.to_backend)
        self.assertIn(f"BUNDLE:END:0:{'0'*64}\n".encode(), relay.to_backend)
        self.assertEqual(relay.held_input, b"typed\r")

    def request(self, identifier="1"):
        return (identifier, "suggest", "echo x", "6", "6", "emacs-standard",
                "host", "user", "/", self.relay.session)

    def test_old_suggestion_result_cannot_edit_a_new_request(self):
        relay = self.relay
        future = Future()
        future.set_result("echo x OLD")
        relay.suggestion_future, relay.suggestion_request = future, "1"
        relay.request, relay.state = self.request("2"), State.WAIT
        relay.poll_suggestion()
        self.assertEqual(relay.to_backend, b"")

    def test_pending_typing_cancels_completed_suggestion_without_losing_input(self):
        relay = self.relay
        future = Future()
        future.set_result("echo x SUGGESTION")
        relay.suggestion_future, relay.suggestion_request = future, "1"
        relay.request, relay.state = self.request(), State.WAIT
        relay.held_input.extend(b"new\r")
        relay.poll_suggestion()
        self.assertIn(b"DONE:cancel\n", relay.to_backend)
        self.assertNotIn(b"DATA:", relay.to_backend)
        self.assertEqual(relay.held_input, b"new\r")

    def test_busy_suggestion_worker_does_not_queue_another_query(self):
        relay = self.relay
        future = Future()
        relay.suggestion_future, relay.suggestion_request = future, "1"
        relay.request, relay.state = self.request("2"), State.WAIT
        relay.open_suggestion(b"")
        self.assertIs(relay.suggestion_future, future)
        self.assertIsNone(relay.suggestion_worker)
        self.assertIn(b"DONE:cancel\n", relay.to_backend)
