"""Bounded import coordination, interruption recovery, and CLI diagnostics."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from atuin_ssh.cli import main
from atuin_ssh.importing import ImportLedger


class BatchNative:
    def __init__(self):
        self.calls = []
        self.records = {}
        self.interrupt = False

    def privacy_batch(self, events):
        self.calls.append(("filter", len(events)))
        return [{"allowed": not value["command"].startswith(" ")} for value in events]

    def batch(self, operation, events):
        self.calls.append((operation, len(events)))
        if operation == "probe":
            return [{"collision": False} for _ in events]
        results = []
        for index, value in enumerate(events):
            if self.interrupt and index == 3:
                self.interrupt = False
                raise KeyboardInterrupt
            previous = self.records.get(value["id"])
            if previous is not None:
                assert value["reconcile"], "uncertain commits must reconcile stable IDs"
            self.records[value["id"]] = value["command"]
            results.append({"state": "committed"})
        return results


class ImportBatchContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = BatchNative()
        self.ledger = ImportLedger(self.root, self.native)
        self.source = {"host": "fixture", "user": "remote", "histfile": "/fixture/history"}

    @staticmethod
    def history(count):
        return "".join(f"#{1700000000 + index}\nprintf 'fixture {index}'\n" for index in range(count)).encode()

    def test_batches_preserve_order_privacy_and_progress_without_command_text(self):
        notifications = []
        raw = self.history(131) + b"#1700000200\n excluded-private-fixture\n"
        result = self.ledger.import_bytes(self.source, raw, progress=notifications.append)
        self.assertEqual((result["imported"], result["filtered"], result["pending"]), (131, 1, 0))
        self.assertTrue(all(0 < size <= 64 for _, size in self.native.calls))
        self.assertEqual(list(self.native.records.values()), [f"printf 'fixture {index}'" for index in range(131)])
        self.assertEqual(notifications[-1], {"phase": "write", "processed": 131, "total": 131, "imported": 131})
        self.assertNotIn("printf", json.dumps(notifications))
        for path in self.root.iterdir():
            if path.is_file():
                self.assertNotIn(b"excluded-private-fixture", path.read_bytes())

    def test_interrupted_partial_batch_reconciles_stable_ids_without_refetch(self):
        self.native.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.ledger.import_bytes(self.source, self.history(70))
        with self.ledger._db() as db:
            states = dict(db.execute("SELECT state,count(*) FROM occurrences GROUP BY state"))
        self.assertEqual(states, {"pending": 6, "writing": 64})
        self.assertEqual(len(self.native.records), 3)
        result = self.ledger.resume()
        self.assertEqual(result, {"imported": 70, "pending": 0})
        self.assertEqual(len(self.native.records), 70)
        self.assertEqual(self.ledger.resume(), {"imported": 0, "pending": 0})

    def test_ctrl_c_returns_130_and_concise_resume_instruction(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        with patch("atuin_ssh.importing.import_history", side_effect=KeyboardInterrupt), redirect_stderr(stderr), redirect_stdout(stdout):
            status = main(["history", "import", "--target", "fixture"])
        self.assertEqual(status, 130)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("atuin-ssh history resume-imports", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_invalid_source_error_does_not_expose_source_bytes(self):
        stderr = io.StringIO()
        private = b"private-fixture-\xff"
        error = UnicodeDecodeError("utf-8", private, len(private) - 1, len(private), "invalid")
        with patch("atuin_ssh.importing.import_history", side_effect=error), redirect_stderr(stderr):
            self.assertEqual(main(["history", "import", "--target", "fixture"]), 2)
        self.assertNotIn("private-fixture", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_concurrent_resume_waits_and_does_not_replace_confirmed_results(self):
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        original = self.native.batch

        def blocking(operation, events):
            if operation == "import":
                entered.set()
                if not release.wait(5):
                    raise AssertionError("fixture writer was not released")
            return original(operation, events)

        self.native.batch = blocking
        first, second, errors = [], [], []

        def run(destination, operation):
            try:
                destination.append(operation())
            except BaseException as error:
                errors.append(error)

        writer = threading.Thread(target=run, args=(first, lambda: self.ledger.import_bytes(self.source, self.history(3))))
        writer.start()
        self.assertTrue(entered.wait(5))
        another = ImportLedger(self.root, self.native)
        waiter = threading.Thread(target=run, args=(second, lambda: another.resume(
            progress=lambda value: waiting.set() if value["phase"] == "wait" else None)))
        waiter.start()
        try:
            self.assertTrue(waiting.wait(5))
        finally:
            release.set()
            writer.join(5)
            waiter.join(5)
        self.assertFalse(writer.is_alive() or waiter.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(first[0]["imported"], 3)
        self.assertEqual(second, [{"imported": 0, "pending": 0}])
        self.assertEqual([call for call in self.native.calls if call[0] == "import"], [("import", 3)])
