import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from atuin_ssh.atuin import Context, NativeAtuin, NativeError
from atuin_ssh.history import Outbox, timestamp_ns
from atuin_ssh.importing import ImportLedger, parse_bash_history


class NativeFixture:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.keys = set()

    def allowed(self, value):
        if self.fail:
            raise NativeError("unavailable")
        return not value["command"].startswith(" ")

    def native(self, operation, value):
        self.calls.append((operation, dict(value)))
        if self.fail:
            raise NativeError("unavailable")
        key = (value["timestamp_ns"], value["cwd"], value["command"])
        if operation == "probe":
            return {"collision": key in self.keys}
        if operation == "start":
            return {"state": "started"}
        if key in self.keys and not value.get("reconcile"):
            return {"state": "collision"}
        self.keys.add(key)
        return {"state": "committed"}


class StorageContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.native = NativeFixture()

    def tearDown(self):
        self.temp.cleanup()

    def event(self, command="printf hello", command_id="shell:1"):
        return {"type": "start", "command_id": command_id, "command": command,
                "host": "destination", "user": "alice", "cwd": "/remote-only",
                "session": "shell", "shell": "bash", "timestamp": "1700000000.123456"}

    def test_authoritative_metadata_and_completion_reach_native(self):
        box = Outbox(self.root, self.native)
        try:
            box.submit(self.event())
            box.submit({"type": "end", "command_id": "shell:1", "status": 17, "timestamp": "1700000000.223456"})
            self.assertTrue(box.barrier(2))
            final = next(value for op, value in self.native.calls if op == "write")
            self.assertEqual(final["timestamp_ns"], "1700000000123456000")
            self.assertEqual(final["duration_ns"], 100_000_000)
            self.assertEqual(final["status"], 17)
            self.assertEqual((final["host"], final["user"], final["cwd"]), ("destination", "alice", "/remote-only"))
        finally:
            box.close()

    def test_privacy_precedes_every_durable_payload(self):
        box = Outbox(self.root, self.native)
        try:
            box.submit(self.event(" private excluded token"))
            self.assertTrue(box.barrier(2))
            with sqlite3.connect(box.path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM commands").fetchone()[0], 0)
            for file in self.root.iterdir():
                self.assertNotIn(b"private excluded", file.read_bytes())
        finally:
            box.close()

    def test_filter_failure_is_visible_without_durable_command(self):
        self.native.fail = True
        box = Outbox(self.root, self.native)
        try:
            box.submit(self.event("credential that cannot be filtered"))
            self.assertFalse(box.barrier(2))
            self.assertEqual(box.status()["rejected_before_durable"], 1)
            with sqlite3.connect(box.path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM commands").fetchone()[0], 0)
        finally:
            box.close()

    def test_wall_clock_reversal_remains_unknown(self):
        box = Outbox(self.root, self.native)
        try:
            box.submit(self.event())
            box.submit({"type": "end", "command_id": "shell:1", "status": 0, "timestamp": "1699999999.000000"})
            self.assertTrue(box.barrier(2))
            final = next(value for op, value in self.native.calls if op == "write")
            self.assertEqual(final["duration_ns"], -1)
        finally:
            box.close()

    def test_uncertain_commit_retries_with_stable_identity(self):
        box = Outbox(self.root, self.native, start_worker=False)
        box._accept(self.event())
        box._accept({"type": "end", "command_id": "shell:1", "status": 0, "timestamp": "1700000001.000000"})
        with box._connect() as db:
            db.execute("UPDATE commands SET state='writing_end',attempts=1")
        box._write_one()
        self.assertTrue(self.native.calls[-1][1]["reconcile"])
        first_id = self.native.calls[-1][1]["id"]
        box._accept(self.event())
        self.assertEqual(box.status()["states"], {"committed": 1})
        self.assertEqual(len(first_id), 32)

    def test_corrupt_outbox_is_quarantined_without_native_write(self):
        box = Outbox(self.root, self.native, start_worker=False)
        box._accept(self.event())
        with box._connect() as db:
            db.execute("UPDATE commands SET payload='changed'")
        box._write_one()
        self.assertEqual(box.status()["states"], {"corrupt": 1})
        self.assertEqual(self.native.calls, [])

    def test_exact_unicode_and_trailing_newline_widget_result(self):
        result = self.root / "result"
        result.write_bytes("__atuin_accept__:printf 'λ'\n\n".encode())
        parsed = NativeAtuin.result(result)
        self.assertEqual((parsed.action, parsed.command), ("accept", "printf 'λ'\n\n"))
        self.assertFalse(result.exists())
        result.write_bytes(b"")
        self.assertEqual(NativeAtuin.result(result).action, "cancel")

    def test_context_changes_only_child_invocation(self):
        base = {"HOME": "/home/hubuser", "ATUIN_HOME": "/state/atuin", "PWD": "/home/hubuser", "ATUIN_SESSION": "hub"}
        remote = Context("remote", "bob", "/absent", "remote-session").environment(base)
        self.assertEqual(base["ATUIN_SESSION"], "hub")
        self.assertEqual(remote["HOME"], base["HOME"])
        self.assertEqual(remote["ATUIN_HOME"], base["ATUIN_HOME"])
        self.assertEqual(remote["PWD"], "/absent")

    def test_timestamped_multiline_and_ambiguous_untimestamped_history(self):
        entries = parse_bash_history(b"echo old\n#1700000000\nprintf 'one\ntwo'\n#1700000001\necho next\n")
        self.assertTrue(entries[0].ambiguous)
        self.assertEqual(entries[1].command, "printf 'one\ntwo'")
        self.assertEqual(entries[1].timestamp_ns, "1700000000000000000")
        self.assertFalse(entries[1].ambiguous)

    def test_import_tracks_occurrences_and_retains_cross_host_collision(self):
        ledger = ImportLedger(self.root, self.native)
        source = {"target": "one", "host": "one", "user": "alice", "histfile": "/home/alice/.bash_history"}
        raw = b"#1700000000\necho repeat\n#1700000001\necho repeat\n"
        first = ledger.import_bytes(source, raw)
        self.assertEqual(first["imported"], 2)
        second = ledger.import_bytes(source, raw + b"#1700000002\necho repeat\n")
        self.assertEqual((second["duplicates"], second["imported"]), (2, 1))
        other = {**source, "target": "two", "host": "two"}
        collision = ledger.import_bytes(other, raw)
        self.assertEqual((collision["imported"], collision["pending"]), (0, 2))
        repeated = ledger.import_bytes(other, raw)
        self.assertEqual(repeated["pending"], 2)

    def test_import_dry_run_does_not_persist_command_or_snapshot(self):
        ledger = ImportLedger(self.root, self.native)
        report = ledger.import_bytes({"host": "h", "user": "u", "histfile": "history"}, b"#1700000000\necho dry-run\n", dry_run=True)
        self.assertEqual(report["pending"], 1)
        with ledger._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM occurrences").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM sources").fetchone()[0], 0)


@unittest.skipUnless(shutil.which("atuin-ssh-native") and shutil.which("atuin-ssh-search"), "version-pinned native binaries unavailable")
class NativeStorageContracts(unittest.TestCase):
    """Real native executable/storage tests; each creates fresh disposable state."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        native_root = self.root / "atuin"
        native_root.mkdir()
        (native_root / "config.toml").write_text('auto_sync=false\nupdate_check=false\nsecrets_filter=true\n[daemon]\nenabled=false\n')
        self.env = patch.dict(os.environ, {"ATUIN_HOME": str(native_root), "ATUIN_CONFIG_DIR": str(native_root),
                                         "ATUIN_SSH_STATE_DIR": str(self.root / "bridge"), "ATUIN_AUTO_SYNC": "false", "ATUIN_UPDATE_CHECK": "false"})
        self.env.start()
        self.native = NativeAtuin()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def entry(self, index, command, host="alpha", user="alice", cwd="/remote/work"):
        return {"id": f"00000000000040008000{index:012x}", "host": host, "user": user,
                "cwd": cwd, "session": "0000000000004000800000000000ffff", "shell": "bash",
                "command": command, "timestamp_ns": str(1700000000000000000 + index * 1_000_000_000),
                "status": 0, "duration_ns": 100_000}

    def query(self, scope, *, workspace=None, cwd="/remote/work"):
        env = Context("alpha", "alice", cwd, "0000000000004000800000000000ffff", workspace=workspace).environment()
        env.update(ATUIN_SSH_REMOTE_CONTEXT="1", ATUIN_SSH_REMOTE_WORKSPACE=workspace or "")
        if workspace:
            env["ATUIN_WORKSPACES"] = "true"
        result = subprocess.run(["atuin-ssh-search", "search", "--filter-mode", scope, "--cmd-only"],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return set(result.stdout.splitlines())

    def test_native_write_replay_and_record_integrity(self):
        event = self.entry(1, "printf NATIVE_COMMIT")
        self.assertTrue(self.native.allowed(event))
        self.assertEqual(self.native.native("start", {k:v for k,v in event.items() if k not in {"status", "duration_ns"}})["state"], "started")
        self.assertEqual(self.native.native("write", event)["state"], "committed")
        replay = self.native.native("write", {**event, "reconcile": True})
        self.assertEqual((replay["state"], replay["reconciled"]), ("committed", True))
        self.assertEqual(self.query("global"), {"printf NATIVE_COMMIT"})
        verify = subprocess.run(["atuin", "store", "verify"], capture_output=True, text=True, timeout=10)
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertTrue(self.native.native("check", {})["compatible"])

    def test_exact_native_account_host_global_directory_workspace(self):
        entries = [self.entry(1, "printf ALICE"), self.entry(2, "printf BOB", user="bob"),
                   self.entry(3, "printf BETA", host="beta"), self.entry(4, "printf CHILD", cwd="/remote/work/child"),
                   self.entry(5, "printf NEIGHBOR", cwd="/remote/work-other")]
        for event in entries:
            self.assertEqual(self.native.native("write", event)["state"], "committed")
        self.assertEqual(self.query("account"), {"printf ALICE", "printf CHILD", "printf NEIGHBOR"})
        self.assertEqual(self.query("host"), {"printf ALICE", "printf BOB", "printf CHILD", "printf NEIGHBOR"})
        self.assertEqual(self.query("global"), {e["command"] for e in entries})
        self.assertEqual(self.query("directory"), {"printf ALICE"})
        self.assertEqual(self.query("workspace", workspace="/remote/work"), {"printf ALICE", "printf CHILD"})

    def test_collision_retained_and_native_privacy_filter(self):
        first = self.entry(1, "printf SAME")
        self.assertEqual(self.native.native("import", first)["state"], "committed")
        second = {**first, "id": self.entry(2, "unused")["id"], "host": "another"}
        self.assertTrue(self.native.native("probe", second)["collision"])
        self.assertEqual(self.native.native("import", second)["state"], "collision")
        self.assertFalse(self.native.allowed(self.entry(3, " excluded command")))

    def test_version_guard_refuses_newer_migration_before_native_open(self):
        event = self.entry(1, "printf PRESERVE")
        self.native.native("write", event)
        databases = list((self.root / "atuin").rglob("history.db"))
        self.assertEqual(len(databases), 1)
        with sqlite3.connect(databases[0]) as db:
            db.execute("INSERT INTO _sqlx_migrations(version,description,success,checksum,execution_time) VALUES(99999999999999,'future',1,X'00',0)")
        with self.assertRaises(NativeError):
            self.native.native("check", {})
        with self.assertRaises(NativeError):
            self.native.native("write", self.entry(2, "printf MUST_NOT_WRITE"))

    def test_tombstone_dominates_replay_with_missing_native_view(self):
        event = self.entry(1, "printf NATIVE_DELETE")
        self.native.native("write", event)
        env = Context("alpha", "alice", "/remote/work", event["session"]).environment()
        deleted = subprocess.run(["atuin", "search", "--filter-mode", "global", "--delete", "--", "NATIVE_DELETE"],
                                 env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        # Fault injection: lose only the disposable materialized history view;
        # the authoritative native record store, including deletion, survives.
        history = next((self.root / "atuin").rglob("history.db"))
        for suffix in ("", "-wal", "-shm"):
            Path(str(history) + suffix).unlink(missing_ok=True)
        reply = self.native.native("write", {**event, "reconcile": True})
        self.assertEqual(reply["state"], "deleted")
        self.assertEqual(self.query("global"), set())

    def test_reconcile_materializes_missing_view_from_native_record(self):
        event = self.entry(1, "printf RESTORE_NATIVE_VIEW")
        self.native.native("write", event)
        history = next((self.root / "atuin").rglob("history.db"))
        for suffix in ("", "-wal", "-shm"):
            Path(str(history) + suffix).unlink(missing_ok=True)
        reply = self.native.native("write", {**event, "reconcile": True})
        self.assertEqual((reply["state"], reply["reconciled"]), ("committed", True))
        self.assertEqual(self.query("global"), {event["command"]})


if __name__ == "__main__":
    unittest.main()
