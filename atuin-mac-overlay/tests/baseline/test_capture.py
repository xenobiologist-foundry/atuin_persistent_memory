"""Actual destination command lifecycle, native rows and immediate visibility."""
from __future__ import annotations

import os
import json
import re
import shlex
import subprocess
import unittest
import uuid

import test_two_hop as flow


@unittest.skipUnless(flow.E2E, "disposable two-hop Compose fixture required")
class CommandLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flow.TwoHopNativeWidget.setUpClass()
        cls.addClassCleanup(flow.TwoHopNativeWidget.doClassCleanups)

    def setUp(self):
        self.shell = flow.TwoHopNativeWidget("test_actual_remote_capture_is_immediately_native_searchable")
        self.shell.setUp()
        self.addCleanup(self.shell.doCleanups)
        self.token = "LIFECYCLE_" + uuid.uuid4().hex

    def barrier(self):
        self.shell.widget()
        self.shell.client.send(b"\x1b")
        self.shell.client.expect(flow.PROMPT)

    def query(self, statement, parameters, path="/state/atuin/data/history.db"):
        # Read as the live database owner: SQLite's WAL auxiliary files may
        # need creating after a checkpoint, which the read-only client mount
        # cannot do. mode=ro still prevents changes to the history database.
        probe = """from contextlib import closing
import json,sqlite3,sys
with closing(sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)) as db:
    rows=db.execute(sys.argv[2],json.loads(sys.argv[3])).fetchall()
print(json.dumps(rows))
"""
        arguments = ["python", "-c", probe, path, statement,
                     json.dumps(parameters, ensure_ascii=False)]
        result = subprocess.run(["/usr/bin/ssh", "-F", str(self.shell.config), self.shell.target,
                                 shlex.join(arguments)], capture_output=True, text=True,
                                timeout=15, check=True)
        return [tuple(row) for row in json.loads(result.stdout)]

    def rows(self):
        return self.query("SELECT command,exit,duration,cwd,session FROM history WHERE command LIKE ? AND deleted_at IS NULL ORDER BY timestamp",
                          ("%"+self.token+"%",))

    def assert_occurrence(self, command, status):
        self.barrier()
        matching = [row for row in self.rows() if row[0] == command]
        self.assertEqual(len(matching), 1, "one submitted compound command must produce one occurrence")
        self.assertEqual(matching[0][1], status)
        self.assertGreaterEqual(matching[0][2], 0)

    def test_pipelines_functions_loops_subshells_and_substitution_are_one_entry(self):
        command = (f"f_{self.token}() {{ for x in a b; do printf '%s' \"$x\"; done; }}; "
                   f"f_{self.token} | cat; : \"$(printf '%s' substitution)\"; (exit 23)")
        self.shell.command(command)
        self.assert_occurrence(command, 23)
        self.assertEqual(len(self.rows()), 1, "internal function/pipeline commands must not be recorded")

    def test_and_or_preserves_observed_status_for_next_command(self):
        command = f": {self.token}; false && printf no || (exit 19)"
        self.shell.command(command)
        output = self.shell.command("printf '\\n__LAST_STATUS__%s__\\n' \"$?\"")
        self.assertIn(b"__LAST_STATUS__19__", output)
        self.assert_occurrence(command, 19)

    def test_repeated_execution_is_not_deduplicated_by_command_text(self):
        command = f"printf '\\n{self.token}\\n'"
        self.shell.command(command)
        self.shell.command(command)
        self.barrier()
        self.assertEqual(len([row for row in self.rows() if row[0] == command]), 2)

    def test_canceled_readline_input_never_becomes_history(self):
        self.shell.client.send(f"printf '{self.token}'")
        self.shell.client.send(b"\x03")
        self.shell.client.expect(flow.PROMPT)
        self.barrier()
        self.assertEqual(self.rows(), [])

    def test_background_completion_is_launch_status(self):
        command = f"(sleep .2; exit 29) & : {self.token}"
        self.shell.command(command)
        self.assert_occurrence(command, 0)

    def test_cwd_is_taken_before_cd_and_new_search_uses_new_cwd(self):
        command = f": {self.token}; cd /tmp"
        self.shell.command(command)
        self.assert_occurrence(command, 0)
        self.assertEqual([row for row in self.rows() if row[0] == command][0][3], "/home/remote")
        second = f"printf '\\n{self.token}_AFTER_CD\\n'"
        self.shell.command(second)
        self.assert_occurrence(second, 0)
        self.assertEqual([row for row in self.rows() if row[0] == second][0][3], "/tmp")

    def test_connection_alias_is_separate_from_actual_native_origin(self):
        command = f": {self.token}"
        self.shell.command(command)
        self.assert_occurrence(command, 0)
        session = self.rows()[0][4]
        target, origin, account = self.query("SELECT target,host,account FROM sessions WHERE session=?",
                                            (session,), "/state/bridge/connections.sqlite3")[0]
        self.assertEqual((target, origin, account), ("remote@destination", "destination", "remote"))

    def test_blank_lines_and_snapshot_binding_do_not_duplicate_previous_entry(self):
        command = f": {self.token}"
        self.shell.command(command)
        self.shell.client.send(b"\n\n")
        self.shell.client.drain(.1)
        self.shell.snapshot()
        self.shell.snapshot()
        self.barrier()
        self.assertEqual(len(self.rows()), 1)

    def test_foreground_bash_read_e_owns_readline_and_its_input_is_not_history(self):
        typed = "FOREGROUND_INPUT_"+uuid.uuid4().hex
        self.shell.client.send("IFS= read -e -r -p '__READ_E__> ' v; printf '\\n__READ_E_VALUE__%s__\\n' \"$v\"\n")
        # Readline 7 does not enable bracketed paste by default. Require the
        # actual foreground prompt, not the same text in the echoed command.
        self.shell.client.expect(re.compile(rb"(?:\r\n|\x1b\[\?2004h)__READ_E__> "))
        self.shell.client.send(typed)
        self.shell.client.send(b"\x12")
        self.shell.client.expect(b"reverse-i-search")
        self.shell.client.send(b"\x07\r")
        self.shell.client.expect(("__READ_E_VALUE__"+typed+"__\r\n").encode())
        self.shell.client.expect(flow.PROMPT)
        self.assertNotRegex(bytes(self.shell.client.transcript), flow.NATIVE_UI)
        self.barrier()
        self.assertEqual(self.query("SELECT count(*) FROM history WHERE command LIKE ?",
                                    ("%"+typed+"%",))[0][0], 0)

    def test_histignore_and_leading_space_are_respected_without_changing_policy(self):
        self.shell.command("HISTIGNORE='*HIDDEN_CAPTURE*'; HISTCONTROL=ignoreboth")
        ignored = f": HIDDEN_CAPTURE_{self.token}"
        self.shell.command(ignored)
        self.shell.command(ignored)
        leading = f" : LEADING_CAPTURE_{self.token}"
        self.shell.command(leading)
        self.shell.command(leading)
        repeated = f": VISIBLE_CAPTURE_{self.token}"
        self.shell.command(repeated)
        self.shell.command(repeated)
        self.barrier()
        commands = [row[0] for row in self.rows()]
        self.assertFalse(any("HIDDEN_CAPTURE_" in row or "LEADING_CAPTURE_" in row for row in commands))
        self.assertEqual(commands.count(repeated), 2)
        output = self.shell.command("printf '\\n__POLICY__%s:%s__\\n' \"$HISTIGNORE\" \"$HISTCONTROL\"")
        self.assertIn(b"__POLICY__*HIDDEN_CAPTURE*:ignoreboth__", output)

    def test_heredoc_is_one_entry_with_multiline_unicode_body(self):
        command = f"cat <<'E2E_END'\n{self.token}\n'é界 quoted'\nE2E_END"
        output = self.shell.command(command)
        self.assertIn(self.token.encode(), output)
        self.barrier()
        entries = self.rows()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][0].rstrip("\n"), command)
        self.assertEqual(entries[0][1], 0)

    def test_history_expansion_records_the_expanded_execution(self):
        command = f"printf '\\n{self.token}\\n'"
        self.shell.command(command)
        output = self.shell.command("!!")
        self.assertIn(self.token.encode(), output)
        self.barrier()
        self.assertEqual([row[0] for row in self.rows()], [command, command])

    def test_alias_invocation_is_one_user_entry(self):
        name = "alias_"+self.token
        self.shell.command(f"alias {name}='printf __ALIAS_EXECUTED__'")
        self.assertIn(b"__ALIAS_EXECUTED__", self.shell.command(name))
        self.barrier()
        entries = [row for row in self.rows() if row[0] == name]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], 0)

    def test_exit_keeps_unknown_completion_instead_of_inventing_success(self):
        command = f": {self.token}; exit 13"
        self.shell.client.send(command+"\n")
        self.shell.client.expect(flow.HUB_PROMPT, timeout=15)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], command)
        self.assertEqual(rows[0][1:3], (-1, -1))

    def test_exec_keeps_unknown_shell_completion(self):
        command = f": {self.token}; exec /bin/true"
        self.shell.client.send(command+"\n")
        self.shell.client.expect(flow.HUB_PROMPT, timeout=15)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], command)
        self.assertEqual(rows[0][1:3], (-1, -1))


if __name__ == "__main__":
    unittest.main()
