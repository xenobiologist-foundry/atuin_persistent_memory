"""Private durable bridge metadata, ordered native writes, and bounded recovery.

This SQLite database is an outbox, never a replacement history/search store.
No raw SQL is issued against any Atuin database.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time
import uuid

from .atuin import NativeAtuin, NativeError, MAX_COMMAND_BYTES

_EVENT_NAMESPACE = uuid.UUID("942e8061-1942-4e93-a08d-d01694b421f3")
TERMINAL = {"committed", "filtered", "deleted"}


def timestamp_ns(value: str | int) -> str:
    """Bash EPOCHREALTIME is decimal seconds; never use float conversion."""
    try:
        result = Decimal(str(value)) * 1_000_000_000
        if not result.is_finite() or result != result.to_integral_value():
            raise ValueError("timestamp precision exceeds nanoseconds")
        return str(int(result))
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("invalid remote timestamp") from exc


def native_event(event: dict) -> dict:
    required = ("command_id", "host", "user", "cwd", "session", "command")
    if any(not isinstance(event.get(key), str) for key in required):
        raise ValueError("incomplete capture metadata")
    if len(event["command"].encode("utf-8")) > MAX_COMMAND_BYTES or any("\0" in event[key] for key in required):
        raise ValueError("invalid command representation")
    value = {key: event[key] for key in ("host", "user", "cwd", "session", "command")}
    value.update(id=uuid.uuid5(_EVENT_NAMESPACE, event["session"] + "\0" + event["command_id"]).hex,
                 shell=event.get("shell", "bash"),
                 timestamp_ns=event.get("timestamp_ns") or timestamp_ns(event["timestamp"]))
    if event.get("status") is not None:
        value["status"] = int(event["status"])
    if event.get("duration_ns") is not None:
        value["duration_ns"] = int(event["duration_ns"])
    return value


def _encode(value: dict) -> tuple[str, str]:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return body, hashlib.sha256(body.encode()).hexdigest()


class Outbox:
    """A bounded memory ingress followed by privacy filtering and durable outbox.

    `submit` means queued in RAM. Only a worker's durable acceptance survives a
    crash. `barrier` waits a bounded interval for search visibility and reports
    every pending/failed state without including command bodies.
    """
    def __init__(self, state_dir: str | Path | None = None, native: NativeAtuin | None = None,
                 *, capacity: int = 512, start_worker: bool = True):
        self.root = Path(state_dir or os.environ.get("ATUIN_SSH_STATE_DIR", os.environ.get("ATUIN_SSH_STATE", "/state/bridge")))
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "outbox.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.native = native or NativeAtuin()
        self.queue: queue.Queue = queue.Queue(maxsize=capacity)
        self.stopping = threading.Event()
        self.rejected = 0
        self.filtered = 0
        self.errors = 0
        self._stats_lock = threading.Lock()
        self._thread = None
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS commands (
                  command_id TEXT PRIMARY KEY, session TEXT NOT NULL,
                  payload TEXT NOT NULL, checksum TEXT NOT NULL,
                  state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                  next_retry REAL NOT NULL DEFAULT 0, updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS pending ON commands(state, next_retry);
                CREATE TABLE IF NOT EXISTS session_sequence (
                  session TEXT PRIMARY KEY, sequence INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS diagnostics (
                  name TEXT PRIMARY KEY, count INTEGER NOT NULL
                );
            """)
        os.chmod(self.path, 0o600)
        if start_worker:
            self._thread = threading.Thread(target=self._run, name="atuin-native-writer", daemon=True)
            self._thread.start()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=0.5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=500")
        return db

    def submit(self, event: dict | str, payload: dict | None = None) -> bool:
        if isinstance(event, str):
            event = {**(payload or {}), "kind": event}
        else:
            event = dict(event)
        try:
            self.queue.put_nowait(event)
            return True
        except queue.Full:
            with self._stats_lock:
                self.rejected += 1
            return False

    enqueue = submit

    def _count(self, name: str):
        # Aggregates retain no excluded body, command ID or source payload.
        with self._connect() as db:
            db.execute("INSERT INTO diagnostics VALUES(?,1) ON CONFLICT(name) DO UPDATE SET count=count+1", (name,))

    def _accept(self, event: dict):
        kind = event.get("kind", event.get("type", "START")).upper()
        command_id = event.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("missing command id")
        with self._connect() as db:
            prior = db.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
            if kind == "START":
                value = native_event(event)
                # Native filter executes with native config and secrets patterns
                # BEFORE any durable command payload or provenance entry exists.
                if not self.native.allowed(value):
                    self.filtered += 1
                    self._count("filtered")
                    return
                if prior:
                    old = self._decode(prior)
                    if any(old.get(k) != v for k, v in value.items()):
                        raise ValueError("command identity conflict")
                    return
                body, checksum = _encode(value)
                db.execute("INSERT INTO commands(command_id,session,payload,checksum,state,updated) VALUES(?,?,?,?,?,?)",
                           (command_id, event["session"], body, checksum, "pending_start", time.time()))
                sequence = event.get("sequence")
                if sequence is not None:
                    db.execute("INSERT INTO session_sequence VALUES(?,?) ON CONFLICT(session) DO UPDATE SET sequence=max(sequence,excluded.sequence)",
                               (event["session"], int(sequence)))
            elif kind == "END":
                if not prior:
                    # Excluded starts create no durable command marker. Never
                    # persist an orphan end as an invented successful command.
                    return
                if prior["state"] in TERMINAL:
                    return
                value = self._decode(prior)
                if "command" not in value:
                    return
                value["status"] = int(event.get("status", event.get("exit", -1)))
                if value["status"] < 0:
                    raise ValueError("invalid observed exit status")
                if event.get("duration_ns") is not None:
                    duration = int(event["duration_ns"])
                else:
                    duration = int(timestamp_ns(event["timestamp"])) - int(value["timestamp_ns"])
                # EPOCHREALTIME is wall clock. A reversal is unknown duration,
                # not a made-up zero; native unknown convention is -1.
                value["duration_ns"] = duration if duration >= 0 else -1
                if not self.native.allowed(value):
                    # Native store_failed applies once the outcome is known.
                    # Scrub the outbox body when that later policy excludes it.
                    body, checksum = _encode({"id": value["id"]})
                    db.execute("UPDATE commands SET payload=?, checksum=?, state='pending_discard',next_retry=0,updated=? WHERE command_id=?",
                               (body, checksum, time.time(), command_id))
                    return
                body, checksum = _encode(value)
                db.execute("UPDATE commands SET payload=?,checksum=?,state='pending_end',next_retry=0,updated=? WHERE command_id=?",
                           (body, checksum, time.time(), command_id))

    @staticmethod
    def _decode(row) -> dict:
        body = row["payload"]
        if hashlib.sha256(body.encode()).hexdigest() != row["checksum"]:
            raise ValueError("outbox checksum mismatch")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("invalid outbox structure")
        return value

    def _write_one(self) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT * FROM commands WHERE state IN ('pending_start','pending_end','pending_discard','writing_start','writing_end','writing_discard') AND next_retry<=? ORDER BY updated LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return False
            command_id = row["command_id"]
            try:
                value = self._decode(row)
            except (ValueError, TypeError):
                db.execute("UPDATE commands SET state='corrupt',updated=? WHERE command_id=?", (time.time(), command_id))
                return True
            operation = "discard" if row["state"].endswith("discard") else "start" if row["state"].endswith("start") else "write"
            value["reconcile"] = row["attempts"] > 0 or row["state"].startswith("writing_")
            db.execute("UPDATE commands SET state=?,attempts=attempts+1,updated=? WHERE command_id=?",
                       ("writing_discard" if operation == "discard" else "writing_start" if operation == "start" else "writing_end", time.time(), command_id))
        try:
            result = self.native.native(operation, value)
            state = result.get("state")
            if state == "started":
                state = "awaiting_end"
            if state not in TERMINAL | {"awaiting_end", "collision"}:
                raise NativeError("unrecognized native commit state")
            with self._connect() as db:
                db.execute("UPDATE commands SET state=?,next_retry=0,updated=? WHERE command_id=?", (state, time.time(), command_id))
        except NativeError:
            # Stable native IDs make a retry reconcilable. Never dedup by text.
            attempts = row["attempts"] + 1
            with self._connect() as db:
                db.execute("UPDATE commands SET state=?,next_retry=?,updated=? WHERE command_id=?",
                           (("pending_discard" if operation == "discard" else "pending_start" if operation == "start" else "pending_end") if attempts < 8 else "failed",
                            time.time() + min(30, 0.1 * 2 ** attempts), time.time(), command_id))
            self.errors += 1
        return True

    def _run(self):
        # One owner across relay processes. Native client/TUI remain independent.
        lock = open(self.root / "writer.lock", "a+b")
        os.chmod(self.root / "writer.lock", 0o600)
        while not self.stopping.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=0.05)
            except queue.Empty:
                event = None
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                if event is not None:
                    try:
                        self._accept(event)
                    except (NativeError, ValueError, UnicodeError, OSError, sqlite3.Error):
                        self.rejected += 1
                        self._count("rejected_before_durable")
                self._write_one()
            except (OSError, sqlite3.Error):
                self.errors += 1
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                if event is not None:
                    self.queue.task_done()
        lock.close()

    def status(self) -> dict:
        with self._connect() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT state,count(*) FROM commands GROUP BY state")}
        return {"states": counts, "queued_volatile": self.queue.unfinished_tasks,
                "rejected_before_durable": self.rejected, "filtered": self.filtered,
                "worker_errors": self.errors}

    def barrier(self, timeout: float = 0.75) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status()
            if not status["queued_volatile"] and not any(status["states"].get(k, 0) for k in ("pending_start", "pending_end", "pending_discard", "writing_start", "writing_end", "writing_discard")):
                return not status["rejected_before_durable"] and not any(status["states"].get(k, 0) for k in ("failed", "collision", "corrupt"))
            time.sleep(0.01)
        return False

    def close(self, timeout: float = 1.0):
        self.stopping.set()
        if self._thread:
            self._thread.join(timeout)

    def retry_failed(self):
        with self._connect() as db:
            db.execute("UPDATE commands SET state=CASE WHEN json_extract(payload,'$.command') IS NULL THEN 'pending_discard' WHEN json_extract(payload,'$.status') IS NULL THEN 'pending_start' ELSE 'pending_end' END, attempts=0,next_retry=0 WHERE state='failed'")


HistoryOutbox = Outbox


def status_directory(path: str | Path | None = None) -> dict:
    root = Path(path or os.environ.get("ATUIN_SSH_STATE_DIR", os.environ.get("ATUIN_SSH_STATE", "/state/bridge")))
    target = root / "outbox.sqlite3"
    if not target.exists():
        return {"states": {}, "pending": 0}
    db = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=0.5)
    try:
        counts = dict(db.execute("SELECT state,count(*) FROM commands GROUP BY state"))
        has_counts = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='diagnostics'").fetchone()
        diagnostics = dict(db.execute("SELECT name,count FROM diagnostics")) if has_counts else {}
        return {"states": counts, "pending": sum(v for k, v in counts.items() if k not in TERMINAL), "diagnostics": diagnostics}
    finally:
        db.close()
