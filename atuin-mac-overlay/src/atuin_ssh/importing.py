"""Explicit, bounded Bash-history import with occurrence provenance.

Timestamp-delimited histories preserve multiline entries. Untimestamped lines
are explicitly ambiguous and receive marked synthetic ordering timestamps.
Native ignored uniqueness inserts remain pending collisions, never successes.
"""
from __future__ import annotations
from .platform import state_root

from dataclasses import dataclass
from contextlib import contextmanager
from difflib import SequenceMatcher
import hashlib
import fcntl
import json
import os
from pathlib import Path
import secrets
import selectors
import shlex
import sqlite3
import subprocess
import time
import uuid
import re
from collections.abc import Callable

from .atuin import NativeAtuin, NativeError, MAX_COMMAND_BYTES


Progress = Callable[[dict], None]
BATCH_SIZE = 64


def _progress(callback: Progress | None, phase: str, **counts):
    if callback is not None:
        callback({"phase": phase, **counts})


def _native_batch(native, operation: str, events: list[dict]) -> list[dict]:
    if hasattr(native, "batch"):
        return native.batch(operation, events)
    return [native.native(operation, event) for event in events]


def _privacy_batch(native, events: list[dict]) -> list[dict]:
    if hasattr(native, "privacy_batch"):
        return native.privacy_batch(events)
    return [native.privacy(event) if hasattr(native, "privacy")
            else {"allowed": native.allowed(event)} for event in events]


@dataclass(frozen=True)
class HistoryEntry:
    command: str
    timestamp_ns: str | None
    line: int
    ambiguous: bool


def parse_bash_history(raw: bytes, max_entries: int = 100_000) -> list[HistoryEntry]:
    if b"\0" in raw:
        raise ValueError("Bash history contains an unrepresentable NUL")
    text = raw.decode("utf-8", "strict")
    # Bash history delimiters are LF bytes. Unicode line separators, CR, VT,
    # and FF may be literal command data and must not create new records.
    pieces = text.split("\n")
    lines = [line + "\n" for line in pieces[:-1]] + (pieces[-1:] if pieces[-1] else [])
    entries = []
    timestamp = None
    pending: list[str] = []
    start = 0

    def flush():
        nonlocal pending
        if pending:
            command = "".join(pending)
            # Remove the history file's one record terminator, preserving any
            # preceding newline within a timestamp-delimited multiline command.
            if command.endswith("\n"):
                command = command[:-1]
            if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
                raise ValueError("history command exceeds supported 256 KiB bound")
            entries.append(HistoryEntry(command, timestamp, start, timestamp is None))
            pending = []
            if len(entries) > max_entries:
                raise ValueError("history exceeds maximum entries")

    for line_number, line in enumerate(lines, 1):
        token = line[:-1] if line.endswith("\n") else line
        if re.fullmatch(r"#-?[0-9]+", token):
            flush()
            timestamp = str(int(token[1:]) * 1_000_000_000)
            start = line_number + 1
        elif timestamp is None:
            if token:
                start = line_number
                pending = [line]
                flush()
        else:
            if not pending:
                start = line_number
            pending.append(line)
    flush()
    return entries


def fetch_history(target: str, *, max_bytes: int = 16 * 1024 * 1024,
                  ssh_options: list[str] | None = None) -> tuple[dict, bytes]:
    if not target or target.startswith("-"):
        raise ValueError("invalid SSH target")
    nonce = secrets.token_hex(16)
    # SSH owns authentication/config/host-key validation. HISTFILE is read only
    # after this account's regular Bash login startup; its content is never code.
    # Give interactive Bash its controlling terminal, then disable PTY byte
    # transformations again after profiles (which may change stty settings).
    # SSH stdin is unused: authentication still uses OpenSSH's own /dev/tty.
    script = ("command stty raw -echo || exit 65; "
              "printf '\\0atuin-ssh-import-" + nonce + "\\0'; "
              "printf '%s\\0' \"$(hostname)\" \"$(id -un)\" \"${HISTFILE-}\"; "
              "if [[ -n ${HISTFILE-} && -r $HISTFILE && -f $HISTFILE ]]; then "
              f"command head -c {int(max_bytes) + 1} -- \"$HISTFILE\"; else exit 66; fi; "
              "printf '\\0atuin-ssh-import-end-" + nonce + "\\0'")
    command = "stty raw -echo && exec bash -lic " + shlex.quote(script)
    process = subprocess.Popen(["/usr/bin/ssh", *(ssh_options or []), "-tt", "--", target, command],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    # Bound startup output as well as content. Refuse noisy/unbounded startup.
    selector = None
    try:
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        output = bytearray()
        deadline = time.monotonic() + 120
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeError("remote history read timed out")
            for key, _ in selector.select(min(remaining, 1)):
                chunk = os.read(key.fd, 65_536)
                if not chunk:
                    selector.unregister(key.fd)
                    break
                output.extend(chunk)
                if len(output) >= max_bytes + 65_536:
                    raise ValueError("remote startup/history exceeds byte limit")
        status = process.wait(timeout=5)
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        if selector is not None:
            selector.close()
        if process.stdout is not None:
            process.stdout.close()
    marker = b"\0atuin-ssh-import-" + nonce.encode() + b"\0"
    position = output.find(marker)
    if status or position < 0:
        raise NativeError("remote history discovery/read failed")
    fields = bytes(output[position + len(marker):]).split(b"\0", 3)
    if len(fields) != 4:
        raise NativeError("remote history metadata incomplete")
    host, user, histfile = (x.decode("utf-8", "strict") for x in fields[:3])
    end_marker = b"\0atuin-ssh-import-end-" + nonce.encode() + b"\0"
    content, separator, _ = fields[3].partition(end_marker)
    if not separator:
        raise NativeError("remote history stream incomplete")
    if len(content) > max_bytes:
        raise ValueError("history exceeds maximum bytes")
    return {"target": target, "host": host, "user": user, "histfile": histfile}, content


class ImportLedger:
    def __init__(self, root: str | Path | None = None, native: NativeAtuin | None = None):
        self.root = Path(root or state_root())
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "imports.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.native = native or NativeAtuin()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (source_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, quality TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS occurrences (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL, checksum TEXT NOT NULL, provenance TEXT NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def import_bytes(self, source: dict, raw: bytes, *, dry_run: bool = False,
                     max_entries: int = 100_000, max_bytes: int = 16 * 1024 * 1024,
                     after_ns: int | None = None, before_ns: int | None = None,
                     progress: Progress | None = None) -> dict:
        if len(raw) > max_bytes:
            raise ValueError("history exceeds maximum bytes")
        if source.get("shell") == "zsh":
            from atuin_layer.local_import import parse_zsh_history
            entries = parse_zsh_history(raw, max_entries)
        else:
            entries = parse_bash_history(raw, max_entries)
        source_id = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        report = {"source": source, "parsed": len(entries), "ambiguous": 0, "synthetic_timestamps": 0,
                  "filtered": 0, "outside_time_bounds": 0, "duplicates": 0,
                  "imported": 0, "pending": 0, "prospective_collisions": 0,
                  "pending_without_payload": 0,
                  "dry_run": dry_run, "limitations": ["Commands held only in other shells' memory are absent.",
                    "Untimestamped multiline boundaries are ambiguous.",
                    "Snapshot rotation with identical repeated occurrences can have ambiguous alignment."]}
        accepted = []
        candidates = []
        base_time = time.time_ns()
        _progress(progress, "privacy", processed=0, total=len(entries))

        def filter_candidates():
            policies = _privacy_batch(self.native, [value[1] for value in candidates])
            if len(policies) != len(candidates):
                raise NativeError("incomplete native privacy response")
            for candidate, policy in zip(candidates, policies):
                if policy.get("pending_unknown_outcome"):
                    report["pending_without_payload"] += 1
                elif not policy.get("allowed"):
                    report["filtered"] += 1
                else:
                    accepted.append(candidate)
            candidates.clear()

        for index, entry in enumerate(entries):
            report["ambiguous"] += int(entry.ambiguous)
            if entry.timestamp_ns is None:
                report["synthetic_timestamps"] += 1
            if (after_ns is not None or before_ns is not None) and entry.timestamp_ns is None:
                report["outside_time_bounds"] += 1
                continue
            if entry.timestamp_ns is not None and ((after_ns is not None and int(entry.timestamp_ns) < after_ns) or (before_ns is not None and int(entry.timestamp_ns) > before_ns)):
                report["outside_time_bounds"] += 1
                continue
            payload = {"id": uuid.uuid4().hex, "host": source["host"], "user": source["user"],
                       "cwd": "unknown", "session": "unknown", "shell": source.get("shell", "bash"), "command": entry.command,
                       "timestamp_ns": entry.timestamp_ns or str(base_time + index),
                       "duration_ns": getattr(entry, "duration_ns", -1), "historical": True}
            fingerprint = hashlib.sha256(json.dumps([entry.timestamp_ns, entry.command], ensure_ascii=False).encode()).hexdigest()
            provenance = {"source_line": entry.line, "timestamp_precision": "seconds" if entry.timestamp_ns else "synthetic_nanosecond_order",
                          "timestamp_synthetic": entry.timestamp_ns is None, "multiline_ambiguous": entry.ambiguous,
                          "cwd": "unknown", "session": "unknown", "exit": "unknown", "duration": "unknown"}
            candidates.append((fingerprint, payload, provenance))
            if len(candidates) == BATCH_SIZE:
                filter_candidates()
                _progress(progress, "privacy", processed=index + 1, total=len(entries))
        if candidates:
            filter_candidates()
        _progress(progress, "privacy", processed=len(entries), total=len(entries))
        with self._db() as db:
            # Serialize snapshot alignment with another explicit importer. Only
            # privacy-approved bodies may enter this transaction or its WAL.
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT snapshot FROM sources WHERE source_id=?", (source_id,)).fetchone()
            snapshot = json.loads(prior[0]) if prior else []
            old_keys = [x[0] for x in snapshot]
            new_keys = [x[0] for x in accepted]
            reuse = {}
            # Occurrence-aligned sequence matching retains repeated commands as
            # repeated entries and handles append, suffix rotation and truncation.
            for block in SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_matching_blocks():
                for n in range(block.size):
                    reuse[block.b + n] = snapshot[block.a + n][1]
            new_snapshot = []
            prospective = set()
            additions = []
            for index, (fingerprint, payload, provenance) in enumerate(accepted):
                existing_id = reuse.get(index)
                if existing_id:
                    report["duplicates"] += 1
                    new_snapshot.append([fingerprint, existing_id])
                    continue
                new_snapshot.append([fingerprint, payload["id"]])
                # Preflight the immutable native uniqueness tuple within this
                # snapshot. Native helper detects collisions with existing DB.
                unique = (payload["timestamp_ns"], payload["command"])
                collision = unique in prospective
                prospective.add(unique)
                additions.append((fingerprint, payload, provenance, collision))
            _progress(progress, "preflight", processed=0, total=len(additions))
            for offset in range(0, len(additions), BATCH_SIZE):
                chunk = additions[offset:offset + BATCH_SIZE]
                results = _native_batch(self.native, "probe", [value[1] for value in chunk])
                if len(results) != len(chunk):
                    raise NativeError("incomplete native preflight response")
                for (fingerprint, payload, provenance, collision), result in zip(chunk, results):
                    report["prospective_collisions"] += bool(collision or result.get("collision", False))
                    if dry_run:
                        continue
                    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    db.execute("INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,0)",
                               (payload["id"], source_id, fingerprint, body, hashlib.sha256(body.encode()).hexdigest(),
                                json.dumps(provenance, sort_keys=True), "pending"))
                _progress(progress, "preflight", processed=min(offset + BATCH_SIZE, len(additions)), total=len(additions))
            if not dry_run:
                db.execute("INSERT INTO sources VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET snapshot=excluded.snapshot,quality=excluded.quality",
                           (source_id, json.dumps(new_snapshot), "timestamp-delimited or explicitly ambiguous"))
        if not dry_run:
            self.resume(source_id, report, progress=progress)
            report["pending"] += report["pending_without_payload"]
        else:
            report["pending"] = len(accepted) - report["duplicates"] + report["pending_without_payload"]
        if report["pending_without_payload"]:
            report["limitations"].append("store_failed=false cannot classify unknown historical exits; these entries have no durable local payload. The source remains unchanged and must be fetched again after an explicit policy change.")
        return report

    def resume(self, source_id: str | None = None, report: dict | None = None, *,
               progress: Progress | None = None) -> dict:
        # One coordinator updates import attempts/states at a time. The native
        # writer lock alone cannot prevent a second coordinator from replacing
        # a confirmed ledger result with an older failed attempt.
        fd = os.open(self.root / "import-resume.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _progress(progress, "wait")
                fcntl.flock(fd, fcntl.LOCK_EX)
            return self._resume_locked(source_id, report, progress=progress)
        finally:
            os.close(fd)

    def _resume_locked(self, source_id: str | None, report: dict | None, *,
                       progress: Progress | None) -> dict:
        counts = report if report is not None else {"imported": 0, "pending": 0}
        source_clause = " AND source_id=?" if source_id else ""
        source_args = (source_id,) if source_id else ()
        with self._db() as db:
            total, through_rowid = db.execute("SELECT count(*),coalesce(max(rowid),0) FROM occurrences WHERE state IN ('pending','writing','failed')" + source_clause,
                                              source_args).fetchone()
        processed = last_rowid = 0
        _progress(progress, "write", processed=0, total=total, imported=counts["imported"])
        while True:
            with self._db() as db:
                rows = db.execute("SELECT rowid AS sequence,* FROM occurrences WHERE rowid>? AND rowid<=? AND state IN ('pending','writing','failed')"
                                  + source_clause + " ORDER BY rowid LIMIT ?", (last_rowid, through_rowid, *source_args, BATCH_SIZE)).fetchall()
            if not rows:
                break
            # Recovery decrypts the authoritative native record stream to check
            # for prior commits and tombstones. A million-record scan can take
            # seconds per entry; keep its deadline and progress independent.
            # Fresh imports still share native setup in bounded batches.
            if rows[0]["attempts"]:
                rows = rows[:1]
            else:
                for index, row in enumerate(rows):
                    if row["attempts"]:
                        rows = rows[:index]
                        break
            last_rowid = rows[-1]["sequence"]
            valid = []
            with self._db() as db:
                for row in rows:
                    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["checksum"]:
                        db.execute("UPDATE occurrences SET state='corrupt' WHERE id=?", (row["id"],))
                        continue
                    value = json.loads(row["payload"])
                    value["reconcile"] = row["attempts"] > 0
                    valid.append((row["id"], value))
                    # Commit all attempts before native writes. An interrupted
                    # batch is reconciled by stable IDs on an explicit resume.
                    db.execute("UPDATE occurrences SET state='writing',attempts=attempts+1 WHERE id=?", (row["id"],))
            try:
                results = _native_batch(self.native, "import", [value for _, value in valid]) if valid else []
                if len(results) != len(valid):
                    raise NativeError("incomplete native import response")
            except NativeError:
                results = [{"state": "failed"}] * len(valid)
            with self._db() as db:
                for (identifier, _), result in zip(valid, results):
                    state = result.get("state", "failed")
                    counts["imported"] += state == "committed"
                    db.execute("UPDATE occurrences SET state=? WHERE id=?", (state, identifier))
            processed += len(rows)
            _progress(progress, "write", processed=processed, total=total, imported=counts["imported"])
        with self._db() as db:
            counts["pending"] = db.execute("SELECT count(*) FROM occurrences WHERE state NOT IN ('committed','deleted','filtered')" + source_clause, source_args).fetchone()[0]
        return counts


def import_history(target: str, *, dry_run: bool = False, max_entries: int = 100_000,
                   max_bytes: int = 16 * 1024 * 1024, state_dir: str | Path | None = None,
                   after_ns: int | None = None, before_ns: int | None = None,
                   progress: Progress | None = None, ssh_options: list[str] | None = None) -> dict:
    _progress(progress, "fetch")
    source, raw = fetch_history(target, max_bytes=max_bytes, ssh_options=ssh_options)
    return ImportLedger(state_dir).import_bytes(source, raw, dry_run=dry_run,
        max_entries=max_entries, max_bytes=max_bytes, after_ns=after_ns, before_ns=before_ns, progress=progress)
