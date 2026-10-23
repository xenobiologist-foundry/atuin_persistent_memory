"""Batch wire limits, recovery deadlines and real native write contracts."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from atuin_ssh.atuin import NativeAtuin, NativeError


class NativeBatchWireContracts(unittest.TestCase):
    def invoke(self, events):
        calls = []

        def reply(argv, **kwargs):
            values = json.loads(kwargs["input"])["events"]
            calls.append((kwargs["input"].encode("utf-8"), kwargs["timeout"], values))
            return SimpleNamespace(returncode=0, stdout=json.dumps({"results": [{"id": event["id"]} for event in values]}))

        with patch("atuin_ssh.atuin.shutil.which", return_value="/synthetic-helper"), patch("atuin_ssh.atuin.subprocess.run", side_effect=reply):
            results = NativeAtuin().batch("filter", events)
        self.assertEqual([result["id"] for result in results], [event["id"] for event in events])
        return calls

    def test_unicode_encoded_wire_stays_within_byte_bound(self):
        calls = self.invoke([{"id": str(index), "command": "😀" * 60_000} for index in range(10)])
        self.assertEqual([len(values) for _, _, values in calls], [4, 4, 2])
        self.assertTrue(all(len(raw) <= 1_048_576 for raw, _, _ in calls))
        self.assertTrue(any(len(raw) > 900_000 for raw, _, _ in calls))

    def test_count_bound_preserves_order(self):
        calls = self.invoke([{"id": str(index)} for index in range(130)])
        self.assertEqual([len(values) for _, _, values in calls], [64, 64, 2])

    def test_uncertain_entries_have_individual_recovery_deadlines(self):
        events = [{"id": str(index), "reconcile": index in {2, 4, 5}} for index in range(6)]
        calls = self.invoke(events)
        self.assertEqual([len(values) for _, _, values in calls], [2, 1, 1, 1, 1])
        self.assertEqual([timeout for _, timeout, _ in calls], [10, 120, 10, 120, 120])

    def test_control_heavy_valid_command_uses_existing_single_event_wire(self):
        calls = []

        def reply(argv, **kwargs):
            event = json.loads(kwargs["input"])
            calls.append((argv[-1], len(kwargs["input"].encode("utf-8"))))
            return SimpleNamespace(returncode=0, stdout=json.dumps({"allowed": True, "id": event["id"]}))

        with patch("atuin_ssh.atuin.shutil.which", return_value="/synthetic-helper"), patch("atuin_ssh.atuin.subprocess.run", side_effect=reply):
            result = NativeAtuin().privacy_batch([{"id": "expanded-json", "command": "\x01" * 262_144}])
        self.assertEqual(result, [{"allowed": True, "id": "expanded-json"}])
        self.assertEqual(calls[0][0], "filter")
        self.assertGreater(calls[0][1], 1_048_576)
        self.assertLessEqual(calls[0][1], 2_097_152)


@unittest.skipUnless(shutil.which("atuin-ssh-native"), "installed pinned native helper required")
class ActualNativeBatchContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="atuin-ssh-native-batch-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = self.root / "native"
        self.profile.mkdir(mode=0o700)
        self.config = self.profile / "config.toml"
        self.config.write_text("auto_sync=false\nupdate_check=false\nstore_failed=true\n[daemon]\nenabled=false\n")
        environ = patch.dict(os.environ, {"ATUIN_HOME": str(self.profile), "ATUIN_CONFIG_DIR": str(self.profile),
                                         "ATUIN_SSH_STATE_DIR": str(self.root / "bridge"), "ATUIN_SESSION": "synthetic-batch"})
        environ.start()
        self.addCleanup(environ.stop)
        self.adapter = NativeAtuin()
        self.timestamp = time.time_ns()

    def event(self, index, command=None):
        return {"id": uuid.uuid4().hex, "host": "synthetic-batch-host", "user": "synthetic-batch-user",
                "cwd": "unknown", "session": "unknown", "shell": "bash", "historical": True,
                "command": command or f"printf BATCH_{index}", "timestamp_ns": str(self.timestamp + index), "duration_ns": -1}

    def test_privacy_order_native_records_and_stable_replay(self):
        events = [self.event(1), self.event(2, " excluded-from-native"), self.event(3)]
        self.assertEqual([value["allowed"] for value in self.adapter.privacy_batch(events)], [True, False, True])
        results = self.adapter.batch("import", events)
        self.assertEqual([value["state"] for value in results], ["committed", "filtered", "committed"])
        replay = self.adapter.batch("import", [{**event, "reconcile": True} for event in events])
        self.assertEqual([value["state"] for value in replay], ["committed", "filtered", "committed"])
        with sqlite3.connect(self.profile / "data/history.db") as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM history").fetchone()[0], 2)
        verified = subprocess.run(["atuin", "store", "verify"], capture_output=True, timeout=10)
        self.assertEqual(verified.returncode, 0, "native record verification failed")

    def test_batch_collision_is_pending_instead_of_silent_success(self):
        first = self.event(1)
        second = {**first, "id": uuid.uuid4().hex}
        results = self.adapter.batch("import", [first, second])
        self.assertEqual([value["state"] for value in results], ["committed", "collision"])

    def test_strict_unknown_import_never_persists_payload(self):
        self.config.write_text("auto_sync=false\nupdate_check=false\nstore_failed=false\n[daemon]\nenabled=false\n")
        event = self.event(1, "STRICT_BATCH_NO_PAYLOAD_" + uuid.uuid4().hex)
        self.assertTrue(self.adapter.privacy_batch([event])[0]["pending_unknown_outcome"])
        self.assertEqual(self.adapter.batch("import", [event])[0]["state"], "pending_unknown_outcome")
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(event["command"].encode(), path.read_bytes(), "strict unknown payload became durable")

    def test_direct_wire_rejects_more_than_64_entries(self):
        with self.assertRaises(NativeError):
            self.adapter.native("filter_batch", {"events": [self.event(index) for index in range(65)]})
