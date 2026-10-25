from __future__ import annotations
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import socket
import signal
import sqlite3
import subprocess
import tempfile
import termios
import time
import unittest
import uuid
from unittest.mock import patch

from pty_client import PTYClient
from atuin_layer.cli import parser
from atuin_layer.local_import import parse_zsh_history
from atuin_ssh.atuin import NativeAtuin, Context

APP = Path(os.environ["ATUIN_LAYER_TEST_APP"])
PROJECT = Path(__file__).resolve().parents[1]


class Parsing(unittest.TestCase):
    def test_final_cli(self):
        for argv in ([], ["doctor"], ["history", "import", "--local", "--dry-run"],
                     ["history", "import", "--target", "server", "--dry-run"], ["history", "resume-imports"]):
            parser().parse_args(argv)
        with self.assertRaises(SystemExit):
            parser().parse_args(["history", "import", "--local", "--target", "server"])

    def test_zsh_extended_multiline_meta_and_unknown(self):
        values = parse_zsh_history(b": 1700000000:2;echo first\\\nsecond  \nplain command\n: 1700000001:0;echo \xd0\x83\xa3\n")
        self.assertEqual([v.command for v in values], ["echo first\nsecond  ", "plain command", "echo Ѓ"])
        self.assertEqual(values[0].timestamp_ns, "1700000000000000000")
        self.assertEqual(values[0].duration_ns, 2000000000)
        self.assertTrue(values[1].ambiguous)


class NativeMac(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="overlay Mac 界 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "Home é"
        self.home.mkdir()
        self.state = self.root / "State 界"
        self.cwd = self.root / "Working directory"
        self.cwd.mkdir()
        self.profile = self.root / "Profile é"
        self.profile.mkdir()
        self.log = self.root / "startup.log"
        for name in [".zshenv", ".zprofile", ".zshrc", ".zlogin"]:
            (self.profile / name).write_text(f"print -r -- {name} >> {str(self.log)!r}\n")
        with (self.profile / ".zshrc").open("a") as stream:
            stream.write("PROMPT='MAC-LOCAL> '\nRPROMPT=''\nHISTFILE=$HOME/fixture-history\nHISTSIZE=1000\nSAVEHIST=1000\nsetopt extended_history\n"
                         "alias overlay_fixture_alias='print ALIAS-PRESERVED'\nssh() { print CUSTOM-SSH-PRESERVED; }\n"
                         "overlay_fixture_function() { print FUNCTION-PRESERVED; }\n")
        self.env = dict(os.environ, HOME=str(self.home), ZDOTDIR=str(self.profile),
                        ATUIN_LAYER_STATE=str(self.state), LC_ALL="en_US.UTF-8", TERM="xterm-256color")
        self.client = None

    def start(self):
        self.client = PTYClient([str(APP / "bin/atuin-layer")], env=self.env)
        self.addCleanup(self.client.close)
        self.client.expect(b"MAC-LOCAL> ", timeout=15)
        return self.client

    def command(self, text):
        self.client.send(text + "\r")
        self.client.expect(b"MAC-LOCAL> ", timeout=20)
        self.client.drain(.15)
        self.client.buffer.clear()

    def rows(self, needle):
        path = self.state / "atuin/history.db"
        if not path.exists():
            return []
        with closing(sqlite3.connect(path)) as database:
            return database.execute("SELECT command,hostname,cwd,session,exit,duration FROM history WHERE command LIKE ? AND deleted_at IS NULL", ("%"+needle+"%",)).fetchall()

    def wait_rows(self, needle, count=1):
        until = time.monotonic() + 8
        while time.monotonic() < until:
            values = self.rows(needle)
            if len(values) >= count:
                return values
            if self.client is not None:
                self.client.read(.02)
            else:
                time.sleep(.02)
        self.fail(f"native history did not contain {count} disposable fixture events")

    def test_first_command_capture_profiles_and_existing_ssh(self):
        c = self.start()
        self.command("print MAC_FIRST_CAPTURE_UNIQUE")
        rows = self.wait_rows("MAC_FIRST_CAPTURE_UNIQUE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "print MAC_FIRST_CAPTURE_UNIQUE")
        self.assertEqual(rows[0][1].split(":")[0], socket.gethostname())
        self.assertTrue(rows[0][3])
        self.assertEqual(self.log.read_text().splitlines(), [".zshenv", ".zprofile", ".zshrc", ".zlogin"])
        c.send("ssh\r")
        c.expect(b"CUSTOM-SSH-PRESERVED")
        c.expect(b"MAC-LOCAL> ")
        c.send("overlay_fixture_alias; overlay_fixture_function\r")
        c.expect(b"ALIAS-PRESERVED")
        c.expect(b"FUNCTION-PRESERVED")

    def test_native_search_insert_and_unicode_cancel(self):
        c = self.start()
        self.command("print MAC_NATIVE_SEARCH_UNIQUE")
        self.wait_rows("MAC_NATIVE_SEARCH_UNIQUE")
        c.send(b"\x12")
        c.expect(b"Search", timeout=10)
        c.send("MAC_NATIVE_SEARCH_UNIQUE")
        c.drain(.25)
        c.send(b"\t")
        c.expect(b"MAC-LOCAL> ", timeout=10)
        c.send(b"\r")
        c.expect(b"MAC_NATIVE_SEARCH_UNIQUE")
        c.expect(b"MAC-LOCAL> ")
        c.drain(.3)
        c.buffer.clear()
        c.send("print 'é界-cancel'")
        c.send(b"\x02\x02\x12")
        c.expect(b"Search", timeout=10)
        c.send(b"\x1b")
        c.expect(b"MAC-LOCAL> ", timeout=10)
        c.drain(.2)
        c.send(b"\x05\r")
        c.expect("é界-cancel".encode())
        self.wait_rows("é界-cancel")

    def test_suggestion_right_accepts_without_executing(self):
        c = self.start()
        marker = self.home / "suggestion-executions"
        command = "print SUGGESTION_MARKER >> " + shlex.quote(str(marker))
        self.command(command)
        self.wait_rows("SUGGESTION_MARKER")
        c.send("print SUGGESTION_")
        c.expect(b"MARKER", timeout=10)
        c.send(b"\x1b[C")
        c.drain(.2)
        self.assertEqual(marker.read_text().splitlines(), ["SUGGESTION_MARKER"])
        c.send(b"\r")
        c.expect(b"MAC-LOCAL> ", timeout=10)
        self.assertEqual(marker.read_text().splitlines(), ["SUGGESTION_MARKER"]*2)

    def test_local_import_repeat_append_multiline_and_unknown_exit(self):
        history = self.home / "import fixture"
        history.write_bytes(b": 1700000000:2;echo ZSH_IMPORT_ONE\\\nsecond\n: 1700000001:0;echo ZSH_IMPORT_REPEAT\n: 1700000002:0;echo ZSH_IMPORT_REPEAT\n")
        env = dict(self.env, ATUIN_LAYER_HISTFILE=str(history))
        def invoke(*args):
            result = subprocess.run([str(APP / "bin/atuin-layer"), "history", "import", "--local", *args], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(invoke("--dry-run")["parsed"], 3)
        self.assertEqual(invoke()["imported"], 3)
        self.assertEqual(invoke()["imported"], 0)
        with history.open("ab") as stream:
            stream.write(b": 1700000003:0;echo ZSH_IMPORT_APPEND\n")
        self.assertEqual(invoke()["imported"], 1)
        rows = self.rows("ZSH_IMPORT")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[4] == -1 for row in rows))
        self.assertIn("echo ZSH_IMPORT_ONE\nsecond", [r[0] for r in rows])

    def test_concurrent_sessions_share_store_but_have_distinct_ids(self):
        c = self.start()
        other = PTYClient([str(APP / "bin/atuin-layer")], env=self.env)
        self.addCleanup(other.close)
        other.expect(b"MAC-LOCAL> ", timeout=15)
        self.command("print SESSION_ONE_UNIQUE")
        other.send("print SESSION_TWO_UNIQUE\r")
        other.expect(b"MAC-LOCAL> ")
        first = self.wait_rows("SESSION_ONE_UNIQUE")[0]
        second = self.wait_rows("SESSION_TWO_UNIQUE")[0]
        self.assertNotEqual(first[3], second[3])

    def test_existing_native_plugin_initialization_has_one_capture_hook(self):
        with (self.profile / ".zshrc").open("a") as stream:
            stream.write('source "$ATUIN_LAYER_ROOT/resources/zsh-autosuggestions/zsh-autosuggestions.zsh"\n'
                         'eval "$(atuin init zsh --disable-ai)"\n'
                         'bindkey -v\n')
        c = self.start()
        self.command("print EXISTING_PROFILE_ONCE")
        self.assertEqual(len(self.wait_rows("EXISTING_PROFILE_ONCE")), 1)
        c.send("print -r -- HOOKS:${#${(M)preexec_functions:#_atuin_preexec}}:${#${(M)precmd_functions:#_atuin_precmd}}\r")
        c.expect(b"HOOKS:1:1")
        c.expect(b"MAC-LOCAL> ")
        c.send(b"\x12")
        c.expect(b"GLOBAL")
        c.send(b"\x1b")
        c.expect(b"MAC-LOCAL> ")

    def test_cancel_preserves_authoritative_zle_buffer_cursor_mark_keymap(self):
        c = self.start()
        snapshot = self.root / "zle snapshot"
        setup = ("overlay_snapshot() { print -r -- \"$BUFFER|$CURSOR|$MARK|$KEYMAP\" > " + shlex.quote(str(snapshot)) +
                 "; }; zle -N overlay_snapshot; bindkey '^X^O' overlay_snapshot")
        self.command(setup)
        c.send("print ")
        c.send(b"\x00")
        c.send("'AAé界ZZ'")
        c.send(b"\x02\x02\x18\x0f")
        c.drain(.25)
        before = snapshot.read_text()
        c.send(b"\x12")
        c.expect(b"Search")
        c.send(b"\x1b")
        c.expect(b"MAC-LOCAL> ")
        c.drain(.1)
        c.send(b"\x18\x0f")
        c.drain(.2)
        self.assertEqual(snapshot.read_text(), before)
        c.send(b"\x03")

    def test_local_privacy_and_failed_status(self):
        self.start()
        self.command(" print PRIVATE_LEADING_SPACE_FIXTURE")
        self.assertFalse(self.rows("PRIVATE_LEADING_SPACE_FIXTURE"))
        self.command("print LOCAL_FAILED_STATUS; false")
        row = self.wait_rows("LOCAL_FAILED_STATUS")[0]
        self.assertEqual(row[4], 1)
        self.assertGreaterEqual(row[5], 0)

    def test_catchable_termination_restores_terminal_and_reaps_child(self):
        c = self.start()
        os.kill(c.pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while not c.closed and time.monotonic() < deadline:
            c.read(.05)
        self.assertTrue(c.closed)
        attributes = termios.tcgetattr(c.fd)
        self.assertTrue(attributes[3] & termios.ICANON)
        self.assertTrue(attributes[3] & termios.ECHO)

    def test_exit_status_reaches_parent_with_modes_restored(self):
        c = PTYClient(["/bin/zsh", "-dfi"], env=self.env)
        self.addCleanup(c.close)
        c.send("PS1='PARENT-SHELL> '; original_modes=$(stty -g)\r")
        c.expect(b"PARENT-SHELL> ")
        c.drain(.1)
        c.buffer.clear()
        c.send(shlex.quote(str(APP / "bin/atuin-layer")) + "\r")
        c.expect(b"MAC-LOCAL> ", timeout=15)
        c.send("exit 37\r")
        c.expect(b"PARENT-SHELL> ")
        c.send("saved_rc=$?; [[ $(stty -g) == $original_modes ]]; print PARENT_RESULT:$saved_rc:$?\r")
        c.expect(b"PARENT_RESULT:37:0")

    def test_native_bind_disable_preference_and_offline_config(self):
        self.env["ATUIN_NOBIND"] = "1"
        c = self.start()
        c.send("bindkey -M emacs '^R'; print CONFIG_FLAGS:$ATUIN_AUTO_SYNC:$ATUIN_AI__ENABLED:$ATUIN_PTY_PROXY__ENABLED\r")
        c.expect(b"history-incremental-search-backward")
        c.expect(b"CONFIG_FLAGS:false:false:false")


@unittest.skipUnless(os.environ.get("ATUIN_LAYER_TEST_REMOTE") == "1", "pass --remote for the owned Compose SSH destination")
class RemoteMac(unittest.TestCase):
    setUp = NativeMac.setUp
    start = NativeMac.start
    rows = NativeMac.rows
    wait_rows = NativeMac.wait_rows

    def fixture(self):
        service = "destination-bash44" if os.environ.get("ATUIN_LAYER_TEST_LEGACY") == "1" else "destination"
        port = subprocess.check_output([os.environ.get("ATUIN_LAYER_TEST_DOCKER", "docker"), "compose", "-f", str(PROJECT / "compose.test.yaml"), "port", service, "22"], text=True).strip().rsplit(":", 1)[1]
        config = self.root / "ssh fixture config"
        config.write_text('Host overlay-fixture overlay-alias\n HostName 127.0.0.1\n User remote\n Port '+port+'\n IdentityFile "'+str(PROJECT / '.build/fixture-keys/id_ed25519')+'"\n IdentitiesOnly yes\n StrictHostKeyChecking accept-new\n UserKnownHostsFile "'+str(self.root / 'known_hosts')+'"\n LogLevel ERROR\n')
        self.config = config
        self.ssh = ["/usr/bin/ssh", "-F", str(config), "overlay-fixture"]

    def remote_command(self, text):
        return subprocess.run([*self.ssh, text], capture_output=True, text=True, check=True, timeout=20)

    def connect(self, *options):
        self.fixture()
        self.start()
        forced = ["--bash"] if os.environ.get("ATUIN_LAYER_TEST_LEGACY") == "1" else []
        self.client.send(shlex.join(["ssh-overlay", *forced, *options, "--", "-F", str(self.config), "overlay-fixture"]) + "\r")
        self.client.expect(b"MAC-REMOTE> ", timeout=45)
        self.client.drain(.3)
        self.client.buffer.clear()

    def remote_line(self, text):
        self.client.send(text + "\r")
        self.client.expect(b"MAC-REMOTE> ", timeout=20)
        self.client.drain(.2)
        self.client.buffer.clear()

    def test_mac_ssh_ble_native_search_suggestions_global_and_cleanup(self):
        self.connect()
        c = self.client
        c.send("printf '\\nEDITOR_STATE__%s|%s|%s__\\n' \"${BLE_ATTACHED-unset}\" \"$_AS_BLE_SESSION_DIR\" \"$_AS_SESSION\"\r")
        found = c.expect(re.compile(rb"\r\nEDITOR_STATE__([^\r\n]+)__\r\n"), timeout=15)
        attached, directory, session = found[1].decode().split("|")
        self.assertEqual(attached, "1", "actual remote ble.sh must be attached")
        c.expect(b"MAC-REMOTE> ")
        c.drain(.2)
        c.buffer.clear()
        self.remote_line("printf 'REMOTE_NATIVE_UNIQUE\\n'")
        row = self.wait_rows("REMOTE_NATIVE_UNIQUE")[0]
        self.assertEqual(row[1], "overlay-fixture:remote")
        self.assertEqual(row[3], session)
        # A full burst must survive SSH/relay/native terminal initialization.
        c.send(b"\x12REMOTE_NATIVE_UNIQUE\t")
        c.expect(b"ACCOUNT", timeout=15)
        c.expect(b"MAC-REMOTE> ", timeout=15)
        c.drain(.15)
        c.send(b"\r")
        c.expect(b"REMOTE_NATIVE_UNIQUE")
        c.expect(b"MAC-REMOTE> ")
        c.drain(.2)
        c.buffer.clear()
        # Typing triggers the editor's ordinary idle suggestion scheduling.
        for character in "printf 'REMOTE_NATIVE_":
            c.send(character)
            c.drain(.035)
        c.expect(b"UNIQUE", timeout=10)
        before = len(self.rows("REMOTE_NATIVE_UNIQUE"))
        c.send(b"\x1b[C")
        c.drain(.2)
        self.assertEqual(len(self.rows("REMOTE_NATIVE_UNIQUE")), before)
        c.send(b"\r")
        c.expect(b"MAC-REMOTE> ")
        self.wait_rows("REMOTE_NATIVE_UNIQUE", before+1)
        c.send("exit\r")
        c.expect(b"MAC-LOCAL> ", timeout=15)
        self.assertEqual(self.remote_command("test ! -d " + shlex.quote(directory)).returncode, 0)
        c.drain(.2)
        c.buffer.clear()
        c.send(b"\x12")
        c.expect(b"GLOBAL")
        c.drain(.25)
        c.send("REMOTE_NATIVE_UNIQUE")
        c.drain(.3)
        c.send(b"\t")
        c.expect(b"MAC-LOCAL> ", timeout=10)
        c.drain(.1)
        c.send(b"\r")
        c.expect(b"REMOTE_NATIVE_UNIQUE")
        c.expect(b"MAC-LOCAL> ")
        local = [r for r in self.wait_rows("REMOTE_NATIVE_UNIQUE", before+2) if r[1].startswith(socket.gethostname()+":")]
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0][0], row[0], "the selected command must be the exact remote entry, not the typed query")
        self.assertEqual(local[0][4], 0, "the selected remote command must execute successfully in local zsh")

    def test_remote_completion_foreground_read_and_gnu_fallback(self):
        self.connect("--no-autosuggest")
        c = self.client
        c.send("printf '%s\\n' /destination-only-completion-d\t\r")
        c.expect(b"/destination-only-completion-directory/")
        c.expect(b"MAC-REMOTE> ")
        c.drain(.2)
        c.buffer.clear()
        c.send("read -r -p 'FOREGROUND_INPUT> ' value; printf '\\nREAD_OK__%s__\\n' \"$value\"\r")
        c.expect(b"FOREGROUND_INPUT> ")
        c.send("PRIVATE_INPUT_FIXTURE\r")
        c.expect(b"READ_OK__PRIVATE_INPUT_FIXTURE__")
        c.expect(b"MAC-REMOTE> ")
        c.drain(.2)
        self.assertFalse(self.rows("PRIVATE_INPUT_FIXTURE"))
        c.send("exit\r")
        c.expect(b"MAC-LOCAL> ")

    def test_remote_import_exact_custom_histfile_and_repeat(self):
        self.fixture()
        marker = "REMOTE_IMPORT_" + uuid.uuid4().hex
        self.remote_command("printf '%s\\n' '#1700000100' " + shlex.quote("echo " + marker) + " > /tmp/disposable-bash-history")
        argv = [str(APP / "bin/atuin-layer"), "history", "import", "--target", "overlay-fixture", "--ssh-config", str(self.config)]
        def invoke(extra):
            p = subprocess.run([*argv, *extra], env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)
        self.assertEqual(invoke(["--dry-run"])["parsed"], 1)
        self.assertEqual(invoke([])["imported"], 1)
        self.assertEqual(invoke([])["duplicates"], 1)

    def test_remote_job_control_fullscreen_resize_and_disconnect(self):
        self.connect()
        c = self.client
        c.send("sleep 30\r")
        c.drain(.3)
        c.send(b"\x1a")
        c.expect(b"Stopped", timeout=10)
        c.expect(b"MAC-REMOTE> ")
        c.send("fg\r")
        c.drain(.2)
        c.send(b"\x03")
        c.expect(b"MAC-REMOTE> ")
        c.resize(30, 100)
        c.drain(.2)
        c.send("stty size\r")
        c.expect(b"30 100")
        c.expect(b"MAC-REMOTE> ")
        c.drain(.2)
        c.buffer.clear()
        begin = len(c.transcript)
        c.send("seq 1 200 | less\r")
        c.expect(b"1", timeout=10)
        c.drain(.2)
        c.send("/123\r")
        c.drain(.2)
        c.send("q")
        c.expect(b"MAC-REMOTE> ", timeout=10)
        self.assertNotIn(b"Atuin v18", bytes(c.transcript[begin:]))
        c.send("kill -HUP $$\r")
        c.expect(b"MAC-LOCAL> ", timeout=15)
        c.send("print LOCAL_AFTER_DISCONNECT\r")
        c.expect(b"MAC-LOCAL> ")
        self.wait_rows("LOCAL_AFTER_DISCONNECT")

    def test_open_ssh_config_jump_and_owned_multiplexing(self):
        self.fixture()
        # OpenSSH 10.2's generated ProxyJump command does not quote a -F path
        # containing spaces. Use its supported path here; preserve original
        # argv in the app rather than rewriting OpenSSH's own command grammar.
        temporary = tempfile.TemporaryDirectory(prefix="overlay-ssh-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        config = Path(temporary.name) / "config"
        config.write_bytes(self.config.read_bytes())
        self.config = config
        control = Path(temporary.name) / "control"
        with self.config.open("a") as stream:
            stream.write('\nHost overlay-via-jump\n HostName 127.0.0.1\n Port 22\n User remote\n ProxyJump overlay-fixture\n IdentityFile "'+str(PROJECT / '.build/fixture-keys/id_ed25519')+'"\n IdentitiesOnly yes\n StrictHostKeyChecking accept-new\n UserKnownHostsFile "'+str(self.root / 'known_hosts')+'"\n LogLevel ERROR\n')
        jumped = subprocess.run([str(APP / "bin/ssh-overlay"), "--", "-F", str(self.config), "overlay-via-jump", "printf JUMP_PASSTHROUGH"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(jumped.returncode, 0, jumped.stderr)
        self.assertEqual(jumped.stdout, "JUMP_PASSTHROUGH")
        master = ["/usr/bin/ssh", "-F", str(self.config), "-S", str(control)]
        created = subprocess.run([*master, "-MNf", "overlay-fixture"], capture_output=True, text=True, timeout=20)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.addCleanup(subprocess.run, [*master, "-O", "exit", "overlay-fixture"], capture_output=True, timeout=10)
        self.start()
        self.client.send(shlex.join(["ssh-overlay", *( ["--bash"] if os.environ.get("ATUIN_LAYER_TEST_LEGACY") == "1" else []), "--", "-F", str(self.config), "-S", str(control), "overlay-fixture"])+"\r")
        self.client.expect(b"MAC-REMOTE> ", timeout=40)
        self.client.send("exit\r")
        self.client.expect(b"MAC-LOCAL> ", timeout=15)
        self.assertEqual(subprocess.run([*master, "-O", "check", "overlay-fixture"], capture_output=True, timeout=10).returncode, 0)


if __name__ == "__main__":
    unittest.main()
