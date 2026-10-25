"""Connection provenance, separate from native command origin and history."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

# Never persist full argv/config, ProxyCommand, environment or credential paths.
CONNECTION_FIELDS = {"hostname", "user", "port", "hostkeyalias", "canonicalizehostname",
                     "proxyjump", "requesttty", "sessiontype"}


class ConnectionRegistry:
    def __init__(self, state_dir=None):
        self.root = Path(state_dir or state_root())
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.root / "connections.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with closing(sqlite3.connect(self.path, timeout=.5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (session TEXT PRIMARY KEY, target TEXT NOT NULL, effective TEXT NOT NULL, host TEXT, account TEXT, created REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS origins ON sessions(host,account)")

    def register(self, session, target, effective):
        value = {key: str(value) for key, value in effective.items() if key in CONNECTION_FIELDS}
        with closing(sqlite3.connect(self.path, timeout=.5)) as db, db:
            db.execute("INSERT INTO sessions VALUES(?,?,?,NULL,NULL,?)", (session, target, json.dumps(value, sort_keys=True), time.time()))

    def origin(self, session, host, account):
        if len(host) > 1024 or len(account) > 1024:
            raise ValueError("invalid remote origin length")
        with closing(sqlite3.connect(self.path, timeout=.5)) as db, db:
            db.execute("UPDATE sessions SET host=?,account=? WHERE session=?", (host, account, session))


def origin_is_ambiguous(root, session, host, account):
    """Detect observed endpoint conflicts without inventing a machine identity.

    Multiple aliases with identical effective endpoint settings share a group.
    Distinct endpoint settings may still reach one machine, so conflicts need
    explicit resolution. Unregistered historical/native sessions remain outside
    this detector. Errors propagate so callers can preserve pending events.
    """
    path = Path(root) / "connections.sqlite3"
    if not path.exists():
        return False

    def endpoint(raw):
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("hostname"), str) or not value["hostname"]:
            raise ValueError("connection endpoint unavailable")
        # HostKeyAlias chooses the trust lookup name, not a different network
        # endpoint. An alias explicitly naming the normal known-host entry must
        # remain equivalent to an otherwise identical direct connection.
        return (value["hostname"].casefold().rstrip("."), str(value.get("port", "22")),
                value.get("proxyjump", "none"))

    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=.5)) as db:
        current = db.execute("SELECT effective FROM sessions WHERE session=? AND host=? AND account=?", (session, host, account)).fetchone()
        if current is None:
            return False
        expected = endpoint(current[0])
        return any(endpoint(row[0]) != expected for row in db.execute("SELECT effective FROM sessions WHERE host=? AND account=?", (host, account)))
