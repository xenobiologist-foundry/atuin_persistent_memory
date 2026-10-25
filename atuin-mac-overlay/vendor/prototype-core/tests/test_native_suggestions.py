"""Real pinned native history suggestions with isolated local Atuin state."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

from atuin_ssh.atuin import Context, NativeAtuin


@unittest.skipUnless(shutil.which("atuin-ssh-native") and shutil.which("atuin-ssh-search"),
                     "version-pinned native binaries unavailable")
class NativeSuggestionContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="atuin-native-suggestion-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        state = self.root / "atuin"
        state.mkdir()
        # Deliberately conflicting defaults: the API must choose native prefix
        # search and exact account scope rather than inheriting global/fuzzy.
        (state / "config.toml").write_text(
            'auto_sync=false\nupdate_check=false\nsecrets_filter=true\n'
            'filter_mode="global"\nsearch_mode="fuzzy"\n[daemon]\nenabled=false\n')
        environment = patch.dict(os.environ, {
            "ATUIN_HOME": str(state), "ATUIN_CONFIG_DIR": str(state),
            "ATUIN_SSH_STATE_DIR": str(self.root / "bridge"),
            "ATUIN_AUTO_SYNC": "false", "ATUIN_UPDATE_CHECK": "false",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.native = NativeAtuin()
        self.context = Context("alpha", "alice", "/remote/project", uuid.uuid4().hex)
        self.index = 0

    def seed(self, command, *, host="alpha", user="alice"):
        self.index += 1
        event = {"id": uuid.uuid4().hex, "host": host, "user": user,
                 "cwd": self.context.cwd, "session": self.context.session,
                 "shell": "bash", "command": command,
                 "timestamp_ns": str(1_700_000_000_000_000_000 + self.index * 1_000_000_000),
                 "status": 0, "duration_ns": 1_000_000}
        self.assertEqual(self.native.native("write", event)["state"], "committed")
        return event

    def test_exact_account_prefix_excludes_newer_other_account_and_host(self):
        command = "echo ACCOUNT_PREFIX_this-account"
        self.seed(command)
        self.seed("echo ACCOUNT_PREFIX_other-account", user="bob")
        self.seed("echo ACCOUNT_PREFIX_other-host", host="beta")
        self.assertEqual(self.native.suggest(self.context, "echo ACCOUNT_PREFIX_"), command)
        self.assertEqual(self.native.suggest(Context("alpha", "bob", "/remote/project", self.context.session),
                                             "echo ACCOUNT_PREFIX_"), "echo ACCOUNT_PREFIX_other-account")
        self.assertEqual(self.native.suggest(Context("beta", "alice", "/remote/project", self.context.session),
                                             "echo ACCOUNT_PREFIX_"), "echo ACCOUNT_PREFIX_other-host")

    def test_quotes_unicode_backslashes_and_trailing_spaces_are_exact(self):
        command = "printf '%s' 'é界\\literal \"quoted\"'  "
        self.seed(command)
        self.assertEqual(self.native.suggest(self.context, "printf '%s' 'é"), command)

    def test_empty_control_mid_command_exact_and_missing_queries_have_no_suggestion(self):
        command = "echo PREFIX_middle-needle_suffix"
        self.seed(command)
        for prefix in ("", "echo\tPREFIX", "echo\nPREFIX", "echo\rPREFIX",
                       "echo\x1bPREFIX", "echo\x7fPREFIX", "middle-needle", command,
                       "echo NO_MATCHING_NATIVE_HISTORY"):
            with self.subTest(prefix=repr(prefix)):
                self.assertEqual(self.native.suggest(self.context, prefix), "")

    def test_multiline_or_control_character_candidate_is_not_an_inline_suggestion(self):
        for command, prefix in (("echo MULTILINE\nsecond line", "echo MULTILINE"),
                                ("echo TAB_RESULT\tvalue", "echo TAB_RESULT")):
            with self.subTest(command=repr(command)):
                self.seed(command)
                self.assertEqual(self.native.suggest(self.context, prefix), "")

    def test_native_deletion_tombstone_excludes_previous_match(self):
        command = "echo DELETED_SUGGESTION_UNIQUE"
        self.seed(command)
        self.assertEqual(self.native.suggest(self.context, "echo DELETED_SUGGESTION_"), command)
        deleted = subprocess.run(["atuin", "search", "--filter-mode", "global", "--delete", "--",
                                  "DELETED_SUGGESTION_UNIQUE"], env=self.context.environment(),
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertEqual(self.native.suggest(self.context, "echo DELETED_SUGGESTION_"), "")

    def test_oversized_unicode_prefix_has_no_inline_suggestion(self):
        prefix = "echo " + "界" * 1_800
        self.seed(prefix + "_suffix")
        self.assertEqual(self.native.suggest(self.context, prefix), "")

    def test_oversized_real_native_reply_is_discarded_and_child_is_reaped(self):
        prefix = "echo LARGE_NATIVE_SUGGESTION_"
        self.seed(prefix + "界" * 30_000)
        # Observe real Popen children, including the native compatibility check;
        # do not substitute process output or a fake native executable.
        original = subprocess.Popen
        children = []

        def spawn(*arguments, **keywords):
            child = original(*arguments, **keywords)
            children.append(child)
            return child

        with patch("atuin_ssh.atuin.subprocess.Popen", side_effect=spawn):
            self.assertEqual(self.native.suggest(self.context, prefix), "")
        searches = [child for child in children
                    if Path(child.args[0]).name == "atuin-ssh-search"]
        self.assertEqual(len(searches), 1, "the real native oversized response must be exercised")
        for child in children:
            self.assertIsNotNone(child.returncode, "an owned native child was not awaited")
            with self.assertRaises(ChildProcessError):
                os.waitpid(child.pid, os.WNOHANG)


if __name__ == "__main__":
    unittest.main()
