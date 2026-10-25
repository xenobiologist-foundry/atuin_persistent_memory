import json
from contextlib import contextmanager
import base64
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import shlex
import select
import time
import tempfile
import threading
import unittest
from unittest.mock import patch

from atuin_ssh.atuin import Context, NativeAtuin, NativeError, MAX_COMMAND_BYTES, ACCEPT_PREFIX, INSERT_PREFIX
from atuin_ssh.history import Outbox, timestamp_ns, status_directory
from atuin_ssh.importing import ImportLedger, parse_bash_history, fetch_history
from atuin_ssh.context import ConnectionRegistry


@contextmanager
def fixture_database(*args, **kwargs):
    db = sqlite3.connect(*args, **kwargs)
    try:
        with db:
            yield db
    finally:
        db.close()


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
            with fixture_database(box.path) as db:
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
            with fixture_database(box.path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM commands").fetchone()[0], 0)
            self.assertEqual(status_directory(self.root)["diagnostics"].get("privacy_filter_failed"), 1)
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
        result.write_bytes(ACCEPT_PREFIX.encode() + b"x" * MAX_COMMAND_BYTES)
        bounded = NativeAtuin.result(result)
        self.assertEqual((bounded.action, len(bounded.command)), ("accept", MAX_COMMAND_BYTES))
        result.write_bytes(ACCEPT_PREFIX.encode() + b"x" * (MAX_COMMAND_BYTES + 1))
        self.assertEqual(NativeAtuin.result(result).action, "cancel")
        result.write_text(INSERT_PREFIX + ACCEPT_PREFIX + "literal")
        self.assertEqual(NativeAtuin.result(result).action, "insert")
        result.write_text(INSERT_PREFIX + ACCEPT_PREFIX + "literal")
        self.assertEqual(NativeAtuin.result(result).command, ACCEPT_PREFIX + "literal")

    def test_context_changes_only_child_invocation(self):
        base = {"HOME": "/home/hubuser", "ATUIN_HOME": "/state/atuin", "PWD": "/home/hubuser", "ATUIN_SESSION": "hub"}
        remote = Context("remote", "bob", "/absent", "remote-session").environment(base)
        self.assertEqual(base["ATUIN_SESSION"], "hub")
        self.assertEqual(remote["HOME"], base["HOME"])
        self.assertEqual(remote["ATUIN_HOME"], base["ATUIN_HOME"])
        self.assertEqual(remote["PWD"], "/absent")

    def test_missing_native_search_component_fails_before_result_allocation_for_all_scopes(self):
        with patch("atuin_ssh.atuin.shutil.which", return_value=None):
            for scope in ("account", "host", "global", "session", "directory", "workspace"):
                with self.subTest(scope=scope), self.assertRaises(NativeError):
                    NativeAtuin().prepare(Context("remote", "bob", "/absent", "remote-session"),
                                          scope=scope, runtime_dir=self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_timestamped_multiline_and_ambiguous_untimestamped_history(self):
        entries = parse_bash_history(b"echo old\n#1700000000\nprintf 'one\ntwo'\n#1700000001\necho next\n")
        self.assertTrue(entries[0].ambiguous)
        self.assertEqual(entries[1].command, "printf 'one\ntwo'")
        self.assertEqual(entries[1].timestamp_ns, "1700000000000000000")
        self.assertFalse(entries[1].ambiguous)
        unicode_control = parse_bash_history("#1700000000\nprintf 'one\u2028two\rthree'\n".encode())
        self.assertEqual(unicode_control[0].command, "printf 'one\u2028two\rthree'")

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

    def test_visibility_snapshot_stays_false_until_native_commit(self):
        entered = threading.Event()
        release = threading.Event()
        native = self.native
        original = native.native

        def delayed(operation, event):
            if operation == "write":
                entered.set()
                if not release.wait(3):
                    raise NativeError("test writer timeout")
            return original(operation, event)

        native.native = delayed
        box = Outbox(self.root, native)
        try:
            box.submit(self.event())
            box.submit({"type": "end", "command_id": "shell:1", "status": 0, "timestamp": "1700000001"})
            self.assertTrue(entered.wait(2))
            self.assertFalse(box.is_visible())
            release.set()
            self.assertTrue(box.barrier(2))
            # The worker updates its nonblocking snapshot after task completion.
            for _ in range(100):
                if box.is_visible():
                    break
                threading.Event().wait(0.001)
            self.assertTrue(box.is_visible())
        finally:
            release.set()
            box.close()

    def test_writer_rechecks_origin_if_endpoint_ambiguity_appears_after_acceptance(self):
        registry = ConnectionRegistry(self.root)
        registry.register("shell", "first", {"hostname": "192.0.2.1", "user": "alice", "port": "22"})
        registry.origin("shell", "destination", "alice")
        box = Outbox(self.root, self.native, start_worker=False)
        box._accept(self.event())
        self.assertEqual(box.status()["states"], {"pending_start": 1})
        registry.register("other", "second", {"hostname": "192.0.2.2", "user": "alice", "port": "22"})
        registry.origin("other", "destination", "alice")
        self.assertTrue(box._write_one())
        self.assertEqual(box.status()["states"], {"pending_identity": 1})
        self.assertEqual(self.native.calls, [])
        box._accept({"type": "end", "command_id": "shell:1", "status": 17, "timestamp": "1700000001"})
        self.assertEqual(box.status()["states"], {"pending_identity": 1})
        self.assertFalse(box.barrier(.1))
        with box._connect() as db:
            stored = json.loads(db.execute("SELECT payload FROM commands").fetchone()[0])
        self.assertEqual(stored["status"], 17)
        self.assertTrue(stored["identity_pending"])


@unittest.skipUnless(shutil.which("atuin-ssh-native") and shutil.which("atuin-ssh-search"), "version-pinned native binaries unavailable")
class NativeStorageContracts(unittest.TestCase):
    """Real native executable/storage tests; each creates fresh disposable state."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        native_root = self.root / "atuin"
        native_root.mkdir()
        (native_root / "config.toml").write_text('auto_sync=false\nupdate_check=false\nsecrets_filter=true\nenter_accept=true\nexit_mode="return-original"\ninline_height=20\n[daemon]\nenabled=false\n')
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
        with fixture_database(databases[0]) as db:
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

    def test_actual_outbox_concurrent_sessions_have_immediate_native_visibility(self):
        bridge = self.root / "bridge"
        first = Outbox(bridge, self.native)
        second = Outbox(bridge, self.native)
        try:
            for index, box in enumerate((first, second), 1):
                session = f"019a0000000070008000{index:012x}"
                box.submit({"type": "start", "command_id": session + ":1", "session": session,
                            "host": "alpha", "user": "alice", "cwd": "/remote/work", "shell": "bash",
                            "command": f"printf CONCURRENT_{index}", "timestamp": str(1700000000 + index) + ".000001"})
                box.submit({"type": "end", "command_id": session + ":1", "status": index,
                            "timestamp": str(1700000000 + index) + ".001001"})
            self.assertTrue(first.barrier(5), first.status())
            self.assertTrue(second.barrier(5), second.status())
            self.assertEqual(self.query("account"), {"printf CONCURRENT_1", "printf CONCURRENT_2"})
        finally:
            first.close()
            second.close()

    def test_native_failed_policy_defers_unknown_entry_before_native_storage(self):
        config = self.root / "atuin" / "config.toml"
        config.write_text(config.read_text().replace("[daemon]", "store_failed=false\n[daemon]"))
        event = self.entry(1, "printf FILTER_FAILED")
        incomplete = {k:v for k,v in event.items() if k not in {"status", "duration_ns"}}
        self.assertTrue(self.native.allowed(incomplete))
        self.assertTrue(self.native.privacy(incomplete)["defer_until_completion"])
        self.assertEqual(self.native.native("start", incomplete)["state"], "deferred")
        self.assertFalse(list((self.root / "atuin").rglob("history.db")))
        self.assertFalse(self.native.allowed({**event, "status": 17}))
        self.assertEqual(self.native.native("discard", {"id": event["id"]})["state"], "filtered")
        self.assertEqual(self.query("global"), set())

    def test_failed_policy_never_writes_failed_or_unknown_command_bodies(self):
        config = self.root / "atuin" / "config.toml"
        config.write_text(config.read_text().replace("[daemon]", "store_failed=false\n[daemon]"))
        box = Outbox(self.root / "bridge", self.native)
        failed_body = "printf FAILED_OUTCOME_RAW_FIXTURE"
        unknown_body = "printf UNKNOWN_OUTCOME_RAW_FIXTURE"

        def start(ident, command):
            return {"type": "start", "command_id": "policy:" + ident, "session": "policy",
                    "host": "alpha", "user": "alice", "cwd": "/remote/work", "shell": "bash",
                    "command": command, "timestamp": "1700000000.000001"}

        def wait_volatile():
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and box.status()["deferred_volatile"] != 1:
                time.sleep(.005)
            self.assertEqual(box.status()["deferred_volatile"], 1)
            self.assertFalse(box.is_visible())

        def assert_absent():
            for file in self.root.rglob("*"):
                if file.is_file():
                    raw = file.read_bytes()
                    self.assertNotIn(failed_body.encode(), raw)
                    self.assertNotIn(unknown_body.encode(), raw)

        try:
            box.submit(start("failed", failed_body))
            wait_volatile()
            assert_absent()
            box.submit({"type": "end", "command_id": "policy:failed", "status": 17, "timestamp": "1700000001.000001"})
            self.assertTrue(box.barrier(3), box.status())
            assert_absent()
            box.submit(start("unknown", unknown_body))
            wait_volatile()
            assert_absent()
        finally:
            box.close()
        assert_absent()
        self.assertEqual(status_directory(self.root / "bridge")["diagnostics"]["deferred_without_completion"], 1)
        self.assertEqual(self.query("global"), set())

    def test_failed_policy_success_is_first_durable_acceptance_with_original_metadata(self):
        config = self.root / "atuin" / "config.toml"
        config.write_text(config.read_text().replace("[daemon]", "store_failed=false\n[daemon]"))
        body = "printf SUCCESS_AFTER_VOLATILE_START"
        box = Outbox(self.root / "bridge", self.native)
        try:
            box.submit({"type": "start", "command_id": "success:1", "session": "success",
                        "host": "alpha", "user": "alice", "cwd": "/remote/work", "shell": "bash",
                        "command": body, "timestamp": "1700000000.123456"})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and box.status()["deferred_volatile"] != 1:
                time.sleep(.005)
            self.assertEqual(box.status()["deferred_volatile"], 1)
            for file in self.root.rglob("*"):
                if file.is_file():
                    self.assertNotIn(body.encode(), file.read_bytes())
            box.submit({"type": "end", "command_id": "success:1", "status": 0,
                        "timestamp": "1700000000.223456"})
            self.assertTrue(box.barrier(3), box.status())
            self.assertEqual(self.query("account"), {body})
            history = next((self.root / "atuin").rglob("history.db"))
            with fixture_database(f"file:{history}?mode=ro", uri=True) as db:
                row = db.execute("SELECT timestamp,exit,duration,hostname,cwd,session FROM history").fetchone()
            self.assertEqual(row, (1700000000123456000, 0, 100_000_000,
                                   "alpha:alice", "/remote/work", "success"))
        finally:
            box.close()

    def test_failed_policy_historical_unknown_exit_has_no_durable_payload(self):
        config = self.root / "atuin" / "config.toml"
        config.write_text(config.read_text().replace("[daemon]", "store_failed=false\n[daemon]"))
        command = "printf HISTORICAL_UNKNOWN_EXIT_RAW_FIXTURE"
        source = {"target": "alpha", "host": "alpha", "user": "alice", "histfile": "/custom/history"}
        raw = ("#1700000001\n" + command + "\n").encode()
        ledger = ImportLedger(self.root / "bridge", self.native)
        for dry_run in (True, False):
            report = ledger.import_bytes(source, raw, dry_run=dry_run)
            self.assertEqual((report["imported"], report["pending"], report["pending_without_payload"]), (0, 1, 1))
        event = {**self.entry(1, command), "historical": True, "status": -1}
        policy = self.native.privacy(event)
        self.assertFalse(policy["allowed"])
        self.assertTrue(policy["pending_unknown_outcome"])
        self.assertEqual(self.native.native("import", event)["state"], "pending_unknown_outcome")
        self.assertFalse(list((self.root / "atuin").rglob("history.db")))
        with ledger._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM occurrences").fetchone()[0], 0)
        for file in self.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(command.encode(), file.read_bytes())
        # Refetching under an explicit policy change preserves the original
        # unknown outcome; it must never be manufactured into a successful exit.
        config.write_text(config.read_text().replace("store_failed=false", "store_failed=true"))
        report = ledger.import_bytes(source, raw)
        self.assertEqual((report["imported"], report["pending"]), (1, 0))
        history = next((self.root / "atuin").rglob("history.db"))
        with fixture_database(f"file:{history}?mode=ro", uri=True) as db:
            self.assertEqual(db.execute("SELECT command,exit,duration FROM history").fetchone(), (command, -1, -1))

    def test_ambiguous_reported_origin_remains_pending_without_native_write(self):
        config = self.root / "atuin" / "config.toml"
        original_config = config.read_text()
        for store_failed in (True, False):
            with self.subTest(store_failed=store_failed):
                config.write_text(original_config.replace("[daemon]", "store_failed=" + str(store_failed).lower() + "\n[daemon]"))
                bridge = self.root / ("bridge-default" if store_failed else "bridge-deferred")
                registry = ConnectionRegistry(bridge)
                for session, endpoint in (("same-origin-a", "192.0.2.1"), ("same-origin-b", "192.0.2.2")):
                    registry.register(session, endpoint, {"hostname": endpoint, "user": "alice", "port": "22"})
                    registry.origin(session, "same-reported-host", "alice")
                box = Outbox(bridge, self.native)
                try:
                    for session in ("same-origin-a", "same-origin-b"):
                        box.submit({"type": "start", "command_id": session + ":1", "session": session,
                                    "host": "same-reported-host", "user": "alice", "cwd": "/remote/work", "shell": "bash",
                                    "command": "printf " + session, "timestamp": "1700000000.000001"})
                        box.submit({"type": "end", "command_id": session + ":1", "status": 0,
                                    "timestamp": "1700000000.001001"})
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and box.status()["queued_volatile"]:
                        time.sleep(.005)
                    self.assertFalse(box.barrier(.1))
                    self.assertFalse(box.is_visible())
                    self.assertEqual(box.status()["states"], {"pending_identity": 2})
                    with box._connect() as db:
                        values = [json.loads(row[0]) for row in db.execute("SELECT payload FROM commands")]
                    self.assertTrue(all(value["identity_pending"] and value["status"] == 0 for value in values))
                    self.assertFalse(list((self.root / "atuin").rglob("history.db")))
                finally:
                    box.close()

    def test_corrupt_origin_registry_retains_allowed_native_capture_as_pending(self):
        bridge = self.root / "bridge"
        bridge.mkdir()
        (bridge / "connections.sqlite3").write_bytes(b"broken provenance fixture")
        box = Outbox(bridge, self.native)
        try:
            box.submit({"type": "start", "command_id": "registry-failure:1", "session": "registry-failure",
                        "host": "alpha", "user": "alice", "cwd": "/remote/work", "shell": "bash",
                        "command": "printf RETAIN_ALLOWED_REGISTRY_FAILURE", "timestamp": "1700000000.000001"})
            box.submit({"type": "end", "command_id": "registry-failure:1", "status": 0,
                        "timestamp": "1700000000.001001"})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and box.status()["queued_volatile"]:
                time.sleep(.005)
            self.assertEqual(box.status()["states"], {"pending_identity": 1})
            self.assertEqual(box.status()["rejected_before_durable"], 0)
            self.assertEqual(box.status()["diagnostics"]["identity_registry_unavailable"], 1)
            self.assertFalse(box.barrier(.1))
            self.assertFalse(list((self.root / "atuin").rglob("history.db")))
            with box._connect() as db:
                stored = json.loads(db.execute("SELECT payload FROM commands").fetchone()[0])
            self.assertEqual((stored["status"], stored["duration_ns"]), (0, 1_000_000))
        finally:
            box.close()

    def test_long_initial_query_uses_inherited_memory_descriptor(self):
        event = self.entry(1, "printf LONG_QUERY_MATCH")
        self.native.native("write", event)
        # Native extended-regex syntax ignores this large whitespace region.
        # It exercises exact transport without crossing stock SQLite's
        # independent LIKE-pattern/expression-tree limits.
        query = "r/(?x)LONG_QUERY_MATCH" + " " * 70_000 + "/"
        argv, env, result = self.native.prepare(Context("alpha", "alice", "/remote/work", event["session"]), query)
        try:
            import socket
            fd = int(env["ATUIN_SSH_QUERY_FD"])
            with socket.socket(fileno=os.dup(fd)) as channel:
                self.assertEqual(channel.recv(100_000, socket.MSG_PEEK).decode(), query)
            self.assertEqual(env["ATUIN_QUERY"], "")
            # Use the same upstream query entry point without opening its TUI,
            # inheriting exactly the descriptor used by pty.fork/exec in relay.
            selected = subprocess.run([argv[0], "search", "--filter-mode", "account", "--cmd-only"],
                                      env=env, pass_fds=(fd,), capture_output=True, text=True, timeout=10)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertEqual(selected.stdout.strip(), event["command"])
        finally:
            self.native.cleanup(result)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_actual_native_ui_tags_literal_accept_prefix_for_insert(self):
        from pty_client import PTYClient
        command = ACCEPT_PREFIX + "printf 'LITERAL_NATIVE_PREFIX'"
        self.native.native("write", self.entry(1, command))
        for key, action in ((b"\t", "insert"), (b"\r", "accept"), (b"\x1b", "cancel")):
            with self.subTest(action=action):
                argv, env, result = self.native.prepare(Context("alpha", "alice", "/remote/work", "0000000000004000800000000000ffff"), "LITERAL_NATIVE_PREFIX")
                read_fd, write_fd = os.pipe()
                os.set_inheritable(write_fd, True)
                os.set_blocking(read_fd, False)
                env["ATUIN_SSH_READY_FD"] = str(write_fd)
                client = PTYClient(argv, env=env)
                os.close(write_fd)
                try:
                    deadline = time.monotonic() + 10
                    ready = b""
                    while b"READY\n" not in ready and time.monotonic() < deadline:
                        client.read(.01)
                        if select.select([read_fd], [], [], 0)[0]:
                            ready += os.read(read_fd, 64)
                    self.assertIn(b"READY\n", ready)
                    client.send(key)
                    exit_status = None
                    while time.monotonic() < deadline:
                        client.read(.01)
                        child, status = os.waitpid(client.pid, os.WNOHANG)
                        if child:
                            exit_status = status
                            client.closed = True
                            break
                    self.assertIsNotNone(exit_status, "native TUI did not return after selection")
                    selected = self.native.result(result, os.waitstatus_to_exitcode(exit_status))
                    self.assertEqual(selected.action, action)
                    self.assertEqual(selected.command, "" if action == "cancel" else command)
                finally:
                    os.close(read_fd)
                    client.close()
                    self.native.cleanup(result)


@unittest.skipUnless(os.environ.get("ATUIN_SSH_IMPORT_E2E") == "1", "dedicated disposable import fixture required")
class ImportCliContracts(unittest.TestCase):
    """Run as the non-root hub account in a dedicated fixture, never production."""
    def setUp(self):
        self.target = os.environ.get("ATUIN_SSH_IMPORT_TARGET", "remote@destination")
        self.source, self.original = fetch_history(self.target)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        native = self.root / "native"
        native.mkdir()
        (native / "config.toml").write_text("auto_sync=false\nupdate_check=false\n[daemon]\nenabled=false\n")
        self.env = patch.dict(os.environ, {"ATUIN_HOME": str(native), "ATUIN_CONFIG_DIR": str(native),
                                         "ATUIN_SSH_STATE_DIR": str(self.root / "bridge")})
        self.env.start()

    def tearDown(self):
        self.seed(self.original)
        self.env.stop()
        self.temp.cleanup()

    def seed(self, raw):
        command = "base64 --decode > " + shlex.quote(self.source["histfile"])
        result = subprocess.run(["/usr/bin/ssh", "--", self.target, command], input=base64.b64encode(raw), capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def cli(self, *args):
        result = subprocess.run(["atuin-ssh", "history", *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_installed_import_cli_custom_histfile_rotation_and_readonly_recovery(self):
        source = ("#1700000100\nprintf 'IMPORT_ONE'\n#1700000101\nprintf 'one\nλtwo'\n"
                  "#1700000102\nprintf 'REPEATED'\n#1700000103\nprintf 'REPEATED'\n"
                  "#1700000104\n excluded-private-fixture\n").encode()
        self.seed(source)
        dry = self.cli("import", "--target", self.target, "--dry-run")
        self.assertEqual((dry["parsed"], dry["filtered"], dry["pending"]), (5, 1, 4))
        self.assertEqual(dry["source"]["histfile"], self.source["histfile"])
        self.assertFalse(list((self.root / "native").rglob("history.db")))
        first = self.cli("import", "--target", self.target)
        self.assertEqual((first["imported"], first["pending"]), (4, 0))
        repeat = self.cli("import", "--target", self.target)
        self.assertEqual((repeat["duplicates"], repeat["imported"]), (4, 0))
        self.seed(source + b"#1700000105\nprintf 'APPENDED'\n")
        appended = self.cli("import", "--target", self.target)
        self.assertEqual((appended["duplicates"], appended["imported"]), (4, 1))
        rotated = b"#1700000102\nprintf 'REPEATED'\n#1700000103\nprintf 'REPEATED'\n#1700000105\nprintf 'APPENDED'\n#1700000106\nprintf 'AFTER_ROTATION'\n"
        self.seed(rotated)
        rotation = self.cli("import", "--target", self.target)
        self.assertEqual((rotation["duplicates"], rotation["imported"]), (3, 1))
        history = next((self.root / "native").rglob("history.db"))
        with fixture_database(f"file:{history}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT timestamp,command,cwd,session,exit,duration,hostname,shell FROM history").fetchall()
        self.assertEqual(len(rows), 6)
        self.assertEqual(sum(row[1] == "printf 'REPEATED'" for row in rows), 2)
        multiline = next(row for row in rows if "λtwo" in row[1])
        self.assertEqual(multiline[:6], (1700000101000000000, "printf 'one\nλtwo'", "unknown", "unknown", -1, -1))
        self.assertEqual(multiline[6:], (self.source["host"] + ":" + self.source["user"], "bash"))
        for file in (self.root / "bridge").iterdir():
            if file.is_file():
                self.assertNotIn(b"excluded-private-fixture", file.read_bytes())
        history.chmod(0o400)
        try:
            self.seed(rotated + b"#1700000107\nprintf 'AFTER_READONLY'\n")
            pending = self.cli("import", "--target", self.target)
            self.assertEqual((pending["imported"], pending["pending"]), (0, 1))
        finally:
            history.chmod(0o600)
        resumed = self.cli("resume-imports")
        self.assertEqual((resumed["imported"], resumed["pending"]), (1, 0))
        verify = subprocess.run(["atuin", "store", "verify"], capture_output=True, text=True, timeout=10)
        self.assertEqual(verify.returncode, 0, verify.stderr)


if __name__ == "__main__":
    unittest.main()
