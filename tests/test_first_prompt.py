"""First destination prompt, with no warm-up command or snapshot setup."""
import json
import os
import re
import shlex
import subprocess
import unittest
import uuid

import test_ssh_integration as ssh_fixture
import test_two_hop as flow


@unittest.skipUnless(flow.E2E, "disposable two-hop Compose fixture required")
class FirstPromptNativeWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ssh_fixture.OpenSSHCompatibility.setUpClass()
        cls.addClassCleanup(ssh_fixture.OpenSSHCompatibility.doClassCleanups)
        cls.config = ssh_fixture.OpenSSHCompatibility.config
        cls.hub = ssh_fixture.OpenSSHCompatibility.hub
        cls.destination = ssh_fixture.OpenSSHCompatibility.destination

    def test_first_destination_ctrl_r_opens_native_ui_before_any_user_command(self):
        self.target = self.hub
        self.client = ssh_fixture.OpenSSHCompatibility.open_hub(self)
        # Seed only on the hub through stock native Atuin. There has been no
        # destination shell, prompt customization, command, or snapshot binding.
        token, _ = flow.TwoHopNativeWidget.seed(self)
        prefix = (["atuin-ssh", "connect", "--bash", "--"]
                  if os.environ.get("ATUIN_SSH_TEST_FORCE_BASH") == "1" else ["ssh"])
        self.client.send(shlex.join([*prefix, self.destination]) + "\n")
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        host = os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        # Fixture PS1 only: permit its normal ANSI color reset around hostname.
        # Production middleware never relies on this terminal-text recognizer.
        prompt = re.compile(re.escape((user + "@" + host).encode())
                            + rb"(?:\x1b\[[0-9;]*m)*:[^\r\n]*\$ ")
        self.client.expect(prompt, timeout=30)
        self.client.send(b"\x12")
        self.client.expect(flow.NATIVE_UI, timeout=20)
        self.client.send(token)
        self.client.expect(token.encode())
        self.client.send(b"\x1b")
        self.client.expect(prompt, timeout=20)

        marker = "FIRST_COMMAND_" + uuid.uuid4().hex
        command = f"printf '\\n{marker}\\n'; (exit 17)"
        self.client.send(command + "\n")
        self.client.expect(("\r\n" + marker + "\r\n").encode(), timeout=15)
        self.client.expect(prompt, timeout=15)
        # Query as the hub's database owner so a live WAL can create/use its
        # ordinary auxiliary files. A read-only client volume cannot do this;
        # immutable=1 would incorrectly hide committed WAL contents.
        probe = r'''from contextlib import closing
import json,sqlite3,sys,time
deadline=time.monotonic()+5
rows=[]
while time.monotonic()<deadline:
    with closing(sqlite3.connect("file:/state/atuin/data/history.db?mode=ro",uri=True)) as db:
        rows=db.execute("SELECT exit,hostname,cwd FROM history WHERE command=? AND deleted_at IS NULL",(sys.argv[1],)).fetchall()
    if rows:
        break
    time.sleep(.01)
print(json.dumps(rows))
'''
        result = subprocess.run(["/usr/bin/ssh", "-F", str(self.config), self.hub,
                                 shlex.join(["python", "-c", probe, command])],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [[17, host + ":" + user, "/home/" + user]])


if __name__ == "__main__":
    unittest.main()
