"""Connection provenance and conservative duplicate-hostname detection."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from atuin_ssh.context import ConnectionRegistry, origin_is_ambiguous


class OriginIdentity(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.registry = ConnectionRegistry(self.directory.name)

    def test_aliases_with_one_effective_endpoint_share_without_private_config(self):
        effective = {"hostname": "SERVER.example.", "port": "22", "user": "remote",
                     "proxycommand": "SECRET_PROXY_VALUE", "identityfile": "/private/key"}
        for session, target in (("one", "production"), ("two", "work-alias")):
            self.registry.register(session, target, {**effective, **({"hostkeyalias": "SERVER.example"} if session == "two" else {})})
            self.registry.origin(session, "reported-host", "remote")
        self.assertFalse(origin_is_ambiguous(self.directory.name, "one", "reported-host", "remote"))
        with closing(sqlite3.connect(self.registry.path)) as db:
            rows = db.execute("SELECT target,effective FROM sessions ORDER BY session").fetchall()
        self.assertEqual([row[0] for row in rows], ["production", "work-alias"])
        self.assertNotIn("proxycommand", json.loads(rows[0][1]))
        self.assertNotIn(b"SECRET_PROXY_VALUE", self.registry.path.read_bytes())
        self.assertNotIn(b"/private/key", self.registry.path.read_bytes())
        self.assertEqual(self.registry.path.stat().st_mode & 0o777, 0o600)

    def test_distinct_endpoints_with_same_reported_origin_are_ambiguous(self):
        for session, endpoint in (("one", "server-one.example"), ("two", "server-two.example")):
            self.registry.register(session, endpoint, {"hostname": endpoint, "port": "22"})
            self.registry.origin(session, "identical-hostname", "same-account")
        self.assertTrue(origin_is_ambiguous(self.directory.name, "one", "identical-hostname", "same-account"))
        self.assertTrue(origin_is_ambiguous(self.directory.name, "two", "identical-hostname", "same-account"))

    def test_unregistered_native_session_has_no_manufactured_mapping(self):
        self.assertFalse(origin_is_ambiguous(self.directory.name, "stock-native", "host", "user"))
        self.assertFalse(origin_is_ambiguous(Path(self.directory.name) / "missing", "stock-native", "host", "user"))


if __name__ == "__main__":
    unittest.main()
