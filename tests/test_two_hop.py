"""Behavioral acceptance through workstation ssh -> hub sshd -> destination.

Run only in the disposable Compose test client with ATUIN_SSH_E2E=1. The actual
installed package, native Atuin TUI, OpenSSH clients/servers and Bash are used.
No project code is installed or executed on the destination except its temporary
Bash integration. Screen matching is used only by this terminal test client;
middleware is required to use authoritative Readline callbacks.
"""

from __future__ import annotations

import os
import base64
import re
import shlex
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import time
import unittest
import uuid

from pty_client import PTYClient


E2E = os.environ.get("ATUIN_SSH_E2E") == "1"
PROMPT = b"__E2E_DEST__> "
GEN_PROMPT = re.compile(rb"__E2E_GENERATION__([0-9]+)____E2E_DEST__> ")
HUB_PROMPT = b"__E2E_HUB__> "
SNAPSHOT = re.compile(rb"\r?\n__E2E_BUFFER__([0-9a-f]*):([0-9]+):(-?[0-9]+)__\r?\n")
# Require the actual installed native UI header after its terminal mouse-mode
# activation. Inline Atuin does not enter an alternate screen or hide cursor.
NATIVE_UI = re.compile(rb"\x1b\[\?1000h.*?Atuin v18\.24\.1", re.S)
SNAPSHOT_SETUP = r'''__e2e_buffer() { local h; h=$(printf %s "$READLINE_LINE" | od -An -v -tx1 | tr -d ' \n'); printf '\n__E2E_BUFFER__%s:%s:%s__\n' "$h" "$READLINE_POINT" "${READLINE_MARK:-0}"; }; bind -m emacs -x '"\C-x\C-o": __e2e_buffer'; bind -m vi-insert -x '"\C-x\C-o": __e2e_buffer'; bind -m vi-command -x '"\C-x\C-o": __e2e_buffer'; __e2e_generation=0; PS1='__E2E_GENERATION__$((__e2e_generation+=1))____E2E_DEST__> '; PS2='__E2E_MORE__> ' '''


@unittest.skipUnless(E2E, "disposable two-hop Compose fixture required (ATUIN_SSH_E2E=1)")
class TwoHopNativeWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="atuin-ssh-client-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        keys = Path(os.environ.get("ATUIN_SSH_TEST_KEYS", "/test-keys"))
        hosts = []
        for alias, name in (("hub", "hub"), ("destination", "destination")):
            key = (keys / f"{name}_host_ed25519.pub").read_text().split()
            hosts.append(f"{alias} {key[0]} {key[1]}\n")
        known = root / "known_hosts"
        known.write_text("".join(hosts))
        cls.config = root / "config"
        cls.config.write_text(
            "Host *\n  BatchMode yes\n  StrictHostKeyChecking yes\n"
            f"  UserKnownHostsFile {known}\n"
            f"  IdentityFile {os.environ.get('ATUIN_SSH_TEST_KEY', '/test-keys/id_ed25519')}\n"
            "  IdentitiesOnly yes\n  ConnectTimeout 10\n",
        )

    def setUp(self):
        if self._testMethodName == "test_bootstrap_leaves_no_destination_project_files":
            self.destination_baseline = self.destination_inventory()
        hub = os.environ.get("ATUIN_SSH_TEST_HUB", "hub")
        hub_user = os.environ.get("ATUIN_SSH_TEST_HUB_USER", "hubuser")
        self.target = f"{hub_user}@{hub}"
        self.client = PTYClient(["/usr/bin/ssh", "-F", str(self.config), "-tt", self.target])
        self.addCleanup(self.client.close)
        # A shell command verifies actual hub login, without depending on its
        # selected hostname/prompt or reading bridge-private protocol frames.
        self.client.send("printf '\\n__E2E_HUB_READY__\\n'\n")
        self.client.expect(b"\r\n__E2E_HUB_READY__\r\n", timeout=30)
        self.client.send("PS1='__E2E_HUB__> '; printf '\\n__E2E_HUB_PROMPT__\\n'\n")
        self.client.expect(b"\r\n__E2E_HUB_PROMPT__\r\n")
        self.client.expect(HUB_PROMPT)
        self.enter_destination()

    def destination_inventory(self) -> bytes:
        destination = os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        # Hash ordinary profile/SSH files and list the rest. Bash's own normal
        # .bash_history persistence is explicitly allowed by the product brief.
        result = subprocess.run(
            ["/usr/bin/ssh", "-F", str(self.config), user+"@"+destination,
             'find "$HOME" -maxdepth 2 -type f ! -name .bash_history -print0 | sort -z | xargs -0 -r sha256sum'],
            capture_output=True, timeout=15, check=True,
        )
        return result.stdout

    def enter_destination(self, options: list[str] | None = None):
        destination = os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        prefix = (["atuin-ssh", "connect", "--bash", "--"]
                  if os.environ.get("ATUIN_SSH_TEST_FORCE_BASH") == "1" else ["ssh"])
        args = [*prefix, *(options or []), user+'@'+destination]
        self.client.send(shlex.join(args)+"\n")
        self.client.drain(.5)
        self.client.send("printf '\\n__E2E_DEST_ORIGIN__%s:%s__\\n' \"$(hostname)\" \"$(id -un)\"\n")
        origin = self.client.expect(re.compile(rb"\r\n__E2E_DEST_ORIGIN__([^:\r]+):([^\r]+)__\r\n"), timeout=30)
        self.assertEqual((origin[1].decode(), origin[2].decode()),
                         (os.environ.get("ATUIN_SSH_TEST_DEST_HOSTNAME", "destination"), user),
                         "onward SSH did not reach the fixture; refusing to run destination setup on the hub")
        self.client.send(SNAPSHOT_SETUP + "; printf '\\n__E2E_SETUP_DONE__\\n'\n")
        self.client.expect(b"\r\n__E2E_SETUP_DONE__\r\n", timeout=30)
        prompt = self.client.expect(GEN_PROMPT, timeout=30)
        self.generation = int(prompt[1])
        self.client.buffer.clear()

    def snapshot(self) -> tuple[str, int, int]:
        self.client.send(b"\x18\x0f")
        found = self.client.expect(SNAPSHOT)
        prompt = self.client.expect(GEN_PROMPT)
        self.generation = max(self.generation, int(prompt[1]))
        return bytes.fromhex(found[1].decode()).decode(), int(found[2]), int(found[3])

    def command(self, command: str, timeout: float = 10) -> bytes:
        self.client.send(command + "\n")
        # An accept-line bind-x may redraw the cached Readline prompt before
        # Bash executes. Only expansion of a genuinely new PS1 increments this
        # test-only counter; never append a command marker that changes history.
        deadline = time.monotonic()+timeout
        output = bytearray()
        while True:
            found = self.client.expect(GEN_PROMPT, timeout=max(.01, deadline-time.monotonic()))
            output.extend(found.string[:found.start()])
            if int(found[1]) > self.generation:
                self.generation = int(found[1])
                return bytes(output)

    def seed(self, *, extra: str = "", command_prefix: str = "") -> tuple[str, str]:
        token = "E2E_" + uuid.uuid4().hex
        command = command_prefix+f"printf '\\n__RUN__%s\\n' {token}" + extra
        # Seed through the *unmodified native CLI* on the hub. This separates
        # the defining widget gate from the later command-capture gate.
        host = os.environ.get("ATUIN_SSH_TEST_DEST", "destination")
        user = os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote")
        prefix = ("env ATUIN_HOME=/state/atuin ATUIN_CONFIG_DIR=/state/atuin "
                  f"ATUIN_HOST_NAME={shlex.quote(host)} ATUIN_HOST_USER={shlex.quote(user)} "
                  f"PWD=/home/{shlex.quote(user)} ATUIN_SESSION=fixture ATUIN_SHELL=bash ")
        start = subprocess.run(
            ["/usr/bin/ssh", "-F", str(self.config), self.target,
             prefix + "atuin history start -- " + shlex.quote(command)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        native_id = start.stdout.strip()
        self.assertRegex(native_id, r"^[a-f0-9-]+$")
        subprocess.run(
            ["/usr/bin/ssh", "-F", str(self.config), self.target,
             prefix + "atuin history end --exit 0 --duration 1000000 -- " + shlex.quote(native_id)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return token, command

    def widget(self, key: bytes = b"\x12", query: str = "") -> float:
        # Plain output comparison is insufficient: require native TUI terminal
        # activation, then the exact unique native history result.
        started = time.monotonic()
        self.client.send(key)
        self.client.expect(NATIVE_UI)
        if query:
            self.client.send(query)
            self.client.expect(query.encode())
        return time.monotonic() - started

    def test_ctrl_r_inserts_into_same_remote_readline(self):
        token, command = self.seed()
        self.widget(query=token)
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        line, point, _ = self.snapshot()
        self.assertEqual(line, command)
        self.assertEqual(point, len(command))
        # Tab must only insert. Clear the line without executing its marker.
        self.client.send(b"\x01\x0b")
        self.assertNotIn(("__RUN__"+token).encode(), self.client.drain(.1))

    def test_native_enter_accept_executes_selection(self):
        token, _ = self.seed()
        self.widget(query=token)
        self.client.send(b"\r")
        self.client.expect(("__RUN__"+token+"\r\n").encode())
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], "")

    def test_cancel_preserves_unicode_buffer_cursor_and_mark(self):
        self.client.send("printf '%s\\n' 'AAé界ZZ'")
        self.client.send(b"\x01" + b"\x06"*8)
        original = self.snapshot()
        self.widget()
        self.client.send(b"\x1b")
        self.client.drain(.15)
        self.assertEqual(self.snapshot(), original)

    def test_native_cancel_preserves_internal_readline_mark(self):
        # Bash 4.4 does not expose READLINE_MARK. Test the editor's real mark
        # through its native exchange-point-and-mark action instead of treating
        # an absent shell variable as a zero-valued mark.
        self.client.send(b"abcdef\x01\x06\x06\x00\x06\x06")
        self.assertEqual(self.snapshot()[:2], ("abcdef", 4))
        self.client.send(b"\x18\x18")
        self.assertEqual(self.snapshot()[:2], ("abcdef", 2))
        self.client.send(b"\x18\x18")
        self.assertEqual(self.snapshot()[:2], ("abcdef", 4))
        self.widget()
        self.client.send(b"\x1b")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[:2], ("abcdef", 4))
        self.client.send(b"\x18\x18")
        self.assertEqual(self.snapshot()[:2], ("abcdef", 2))

    def test_up_invokes_native_widget(self):
        self.widget(key=b"\x1b[A")
        self.client.expect(b"SESSION")
        self.client.send(b"\x1b")
        # An unfiltered result may display SNAPSHOT_SETUP itself, including
        # the literal PROMPT text. Require the expanded numeric generation so
        # the snapshot keys cannot be sent while that native result is shown.
        self.client.expect(GEN_PROMPT)
        self.assertEqual(self.snapshot()[0], "")

    def test_immediate_typeahead_owned_by_widget(self):
        token, command = self.seed()
        # Send activation and query together. These bytes may reach the remote
        # tty before its callback reaches the relay, exercising the handover.
        self.client.send(b"\x12" + token.encode())
        self.client.expect(NATIVE_UI)
        self.client.expect(token.encode())
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)

    def test_foreground_read_keeps_its_control_r_and_arrow(self):
        # Bash read has its own line editor only with -e; here raw read consumes
        # literal control bytes, and bridge shell callbacks must stay dormant.
        self.client.send("IFS= read -r -n 4 v; printf '\\n__RAW__'; printf %s \"$v\" | od -An -v -tx1; printf '__RAW_END__\\n'\n")
        self.client.drain(.2)
        self.client.send(b"\x12\x1b[A")
        found = self.client.expect(b"__RAW_END__\r\n")
        self.assertIn(b"12 1b 5b 41", found.string)
        self.assertNotRegex(found.string, NATIVE_UI)

    def test_resize_propagates_across_both_hops(self):
        self.client.resize(41, 137)
        self.client.drain(.1)
        self.client.send("stty size; printf '\\n__SIZE_DONE__\\n'\n")
        output = self.client.expect(b"\r\n__SIZE_DONE__\r\n")
        self.assertIn(b"41 137", output.string)

    def test_resize_during_native_ui_preserves_selection_and_remote_size(self):
        token, command = self.seed(extra="; : 'é界'")
        self.widget(query=token)
        # SIGWINCH must reach the foreground native PTY while remote Bash is
        # waiting, then the destination must receive the current size on return.
        self.client.resize(43, 101)
        self.client.drain(.1)
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)
        self.client.send(b"\x01\x0b")
        output = self.command("stty size")
        self.assertIn(b"43 101\r\n", output)

    def test_shell_context_and_return_to_hub(self):
        output = self.command("printf '\\n__CONTEXT__%s:%s:%s__\\n' \"$(hostname)\" \"$(id -un)\" \"$PWD\"")
        self.assertIn(b"__CONTEXT__", output)
        self.assertIn(os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote").encode()+b":", output)
        self.client.send("exit\n")
        self.client.drain(.2)
        self.client.send("printf '\\n__BACK__%s:%s__\\n' \"$(hostname)\" \"$(id -un)\"\n")
        found = self.client.expect(re.compile(rb"\r\n__BACK__([^:]+):([^_]+)__\r\n"))
        self.assertEqual(found[2].decode(), os.environ.get("ATUIN_SSH_TEST_HUB_USER", "hubuser"))

    def test_partial_query_and_unicode_selected_command(self):
        token, command = self.seed(extra="; : 'é界'")
        self.client.send(token)
        self.widget()
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        line, point, _ = self.snapshot()
        self.assertEqual(line, command)
        # Measure the shell's own cursor unit for the same typed Unicode line.
        selected_point = point
        self.client.send(b"\x01\x0b")
        self.client.send(command)
        self.assertEqual(self.snapshot()[1], selected_point)

    def test_multiline_selection_preserves_trailing_newlines(self):
        token, command = self.seed(extra="; : 'é界'\n\n")
        self.widget(query=token)
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)

    def test_vi_insert_ctrl_r_inserts(self):
        token, command = self.seed()
        self.command("set -o vi")
        bindings = self.command("bind -m vi-insert -s")
        self.assertIn(b'"\\C-r":', bindings, bindings.decode(errors="replace"))
        self.widget(query=token)
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)

    def test_vi_command_slash_cancel_preserves_input(self):
        self.command("set -o vi")
        self.client.send("é界buffer")
        self.client.send(b"\x1b")
        self.client.drain(.1)
        before = self.snapshot()
        self.widget(key=b"/")
        # Vim-normal native TUI uses Escape to leave, preserving the remote
        # vi-command keymap and original editor state.
        self.client.send(b"\x1b")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot(), before)

    def test_custom_readline_binding_after_init_remains_authoritative(self):
        self.command(r'''bind '"\C-r": "CUSTOM_KEY"' ''')
        self.client.send(b"\x12")
        self.assertEqual(self.snapshot()[0], "CUSTOM_KEY")
        self.assertNotRegex(bytes(self.client.buffer), NATIVE_UI)

    def test_ordinary_editing_bracketed_paste_undo_and_completion(self):
        self.client.send(b"\x1b[200~printf '%s\\n' 'a b'\x1b[201~")
        self.assertEqual(self.snapshot()[0], "printf '%s\\n' 'a b'")
        self.client.send(b"\x01\x0b")
        self.client.send("printf x")
        self.client.send(b"\x7f\x1f")  # delete then native undo
        self.assertEqual(self.snapshot()[0], "printf x")
        self.client.send(b"\x01\x0b")
        self.client.send("/bin/pri\t")
        self.assertTrue(self.snapshot()[0].startswith("/bin/print"))

    def test_nested_bash_keeps_its_own_readline_and_return(self):
        self.client.send("bash --noprofile --norc\n")
        self.client.send("printf '\\n__INNER_READY__\\n'\n")
        self.client.expect(b"\r\n__INNER_READY__\r\n")
        self.client.send(b"\x12")
        self.client.expect(b"reverse-i-search")
        self.client.send(b"\x07")
        self.client.drain(.1)
        self.client.send(b"\x03")
        self.client.drain(.1)
        self.client.send("exit\n")
        self.client.expect(PROMPT)
        self.widget()
        self.client.send(b"\x1b")
        self.client.expect(PROMPT)

    def test_immediate_typeahead_with_150_and_300_ms_added_destination_rtt(self):
        self.assert_delayed_destination_typeahead((150, 300))

    def test_immediate_typeahead_with_50_ms_added_destination_rtt(self):
        self.assert_delayed_destination_typeahead((50,))

    def assert_delayed_destination_typeahead(self, rtts):
        code = base64.b64encode(Path(__file__).with_name("latency_proxy.py").read_bytes()).decode()
        for rtt_ms in rtts:
            with self.subTest(added_destination_rtt_ms=rtt_ms):
                self.client.send("exit\n")
                self.client.expect(b"Connection to destination closed.")
                self.client.expect(HUB_PROMPT)
                self.client.send("printf '\\n__HUB_BARRIER__\\n'\n")
                self.client.expect(b"\r\n__HUB_BARRIER__\r\n")
                script = f"import base64;exec(base64.b64decode({code!r}))"
                proxy = f"/usr/local/bin/python -c {shlex.quote(script)} %h %p {rtt_ms/2}"
                self.enter_destination(["-o", "ProxyCommand="+proxy])
                token, command = self.seed()
                self.client.send(b"\x12"+token.encode())
                self.client.expect(NATIVE_UI, timeout=15)
                self.client.expect(token.encode(), timeout=15)
                self.client.send(b"\t")
                self.client.expect(PROMPT, timeout=15)
                self.assertEqual(self.snapshot()[0], command)
                self.client.send(b"\x01\x0b")

    def test_bootstrap_leaves_no_destination_project_files(self):
        output = self.command("command -v atuin || printf '__NO_ATUIN__\\n'; command -v atuin-ssh || printf '__NO_BRIDGE__\\n'")
        self.assertIn(b"__NO_ATUIN__", output)
        self.assertIn(b"__NO_BRIDGE__", output)
        self.widget()
        self.client.send(b"\x1b")
        self.client.expect(PROMPT)
        self.client.send("exit\n")
        self.client.expect(HUB_PROMPT)
        self.assertEqual(self.destination_inventory(), self.destination_baseline)

    def test_actual_remote_capture_is_immediately_native_searchable(self):
        token = "CAPTURE_"+uuid.uuid4().hex
        command = f"printf '\\n__CAPTURED__%s\\n' {token}; (exit 17)"
        self.command(command)
        self.client.send(token)
        self.widget()
        self.client.expect(b"ACCOUNT")
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)
        # Read-only inspection substantiates native metadata; the candidate was
        # already proven visible through Atuin's actual native UI above.
        db = Path("/test-state/atuin/data/history.db")
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT hostname,cwd,exit,duration,session FROM history WHERE command=? AND deleted_at IS NULL",
                (command,),
            ).fetchall()
        self.assertEqual(len(rows), 1, "one accepted compound command must be one native occurrence")
        host, cwd, status, duration, session = rows[0]
        self.assertEqual(host, "destination:"+os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote"))
        self.assertEqual(cwd, "/home/"+os.environ.get("ATUIN_SSH_TEST_DEST_USER", "remote"))
        self.assertEqual(status, 17)
        self.assertGreaterEqual(duration, 0)
        self.assertTrue(session)

    def test_two_workstations_share_central_hub_native_account_history(self):
        peer = TwoHopNativeWidget("test_two_workstations_share_central_hub_native_account_history")
        self.addCleanup(peer.doCleanups)
        peer.setUp()
        token = "SHARED_"+uuid.uuid4().hex
        command = f"printf '\\n__SHARED__%s\\n' {token}"
        peer.command(command)
        # The first workstation must see the peer's occurrence through the
        # one hub's native store, in ACCOUNT scope across distinct sessions.
        self.client.send(token)
        self.widget()
        self.client.expect(b"ACCOUNT")
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)

    def test_native_hub_disabled_bindings_are_preserved_on_destination(self):
        self.client.send("exit\n")
        self.client.expect(HUB_PROMPT)
        explicit_environment = ("export ATUIN_SSH_DISABLE_CTRL_R=1 ATUIN_SSH_DISABLE_UP=1; "
                                if os.environ.get("ATUIN_SSH_TEST_FORCE_BASH") == "1" else "")
        self.client.send("__atuin_bind_ctrl_r=false; __atuin_bind_up_arrow=false; " + explicit_environment
                         + "printf '\\n__DISABLED_SET__\\n'\n")
        self.client.expect(b"\r\n__DISABLED_SET__\r\n")
        self.client.expect(HUB_PROMPT)
        self.enter_destination()
        output = self.command("bind -q reverse-search-history")
        self.assertIn(b"\\C-r", output)
        self.client.send(b"\x12")
        result = self.client.expect(b"reverse-i-search")
        self.assertNotRegex(result.string, NATIVE_UI)
        self.client.send(b"\x07")

    def test_activation_query_navigation_and_tab_in_one_burst(self):
        group = "NAVGROUP_"+uuid.uuid4().hex
        _, command = self.seed(extra="; : "+group)
        self.seed(extra="; : "+group)
        # Atuin's native Down at the newest row exits with return-original.
        # Use Up among two matches to exercise navigation without that action.
        self.client.send(b"\x12"+group.encode()+b"\x1b[A\t")
        self.client.expect(NATIVE_UI)
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)

    def test_activation_query_and_enter_burst_executes_native_selection(self):
        token, _ = self.seed()
        self.seed()
        self.client.send(b"\x12"+token.encode()+b"\r")
        self.client.expect(NATIVE_UI)
        self.client.expect(("__RUN__"+token+"\r\n").encode())
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], "")

    def test_query_and_enter_burst_after_native_header(self):
        token, _ = self.seed()
        self.seed()
        self.widget()
        self.client.send(token.encode()+b"\r")
        self.client.expect(("__RUN__"+token+"\r\n").encode())
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], "")

    def test_selection_above_canonical_limit_preserves_unicode_quotes_and_trailing_lf(self):
        payload = ("é界'\"\\literal\t\n"*1000)
        token, command = self.seed(extra="; : "+shlex.quote(payload)+"\n\n")
        self.assertGreater(len(command.encode()), 16_384)
        self.assertLess(len(command.encode()), 65_536)
        self.widget(query=token)
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        line, point, _ = self.snapshot()
        self.assertEqual(line, command)
        self.assertGreater(point, 4096)

    def test_query_navigation_and_tab_burst_after_native_header(self):
        group = "NAVGROUP_"+uuid.uuid4().hex
        _, command = self.seed(extra="; : "+group)
        self.seed(extra="; : "+group)
        self.widget()
        self.client.send(group.encode()+b"\x1b[A\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)

    def test_native_result_tags_preserve_literal_accept_prefix(self):
        token, command = self.seed(command_prefix="__atuin_accept__:")
        self.widget(query=token)
        self.client.send(b"\t")
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], command)
        self.client.send(b"\x01\x0b")
        self.command("function __atuin_accept__:printf { printf '\\n__LITERAL_PREFIX_USED__\\n'; builtin printf \"$@\"; }")
        self.widget(query=token)
        self.client.send(b"\r")
        self.client.expect(b"\r\n__LITERAL_PREFIX_USED__\r\n")
        self.client.expect(("__RUN__"+token+"\r\n").encode())
        self.client.expect(PROMPT)
        self.assertEqual(self.snapshot()[0], "")


if __name__ == "__main__":
    unittest.main()
