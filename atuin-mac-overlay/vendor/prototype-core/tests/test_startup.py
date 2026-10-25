"""Login startup probes in isolated HOME directories, without fixture mutation.

These are real local Bash PTYs in Linux containers. They prove the bootstrap
startup surface independently; the two-hop suite separately establishes SSH.
"""

import os
from pathlib import Path
import re
import shlex
import tempfile
import unittest

from atuin_ssh.bootstrap import remote_command
from atuin_ssh.protocol import Frame, FrameParser, response
from pty_client import PTYClient


PROMPT = b"__STARTUP_PROMPT__> "
STATE = re.compile(rb"\r\n__STATE__([0-9]+):([0-9]+):([^:]*):([^:]+)__\r\n")
NON_BASH_NOTICE = (b"atuin-ssh: configured login shell is not Bash; native history integration is unavailable, "
                   b"continuing with the ordinary login shell")
OLD_BASH_NOTICE = (b"atuin-ssh: Bash 5 or newer is required for native history integration; "
                   b"continuing with an ordinary Bash login shell")
OLD_CLOCK_NOTICE = (b"atuin-ssh: Bash 4.4 clock support is unavailable; "
                    b"continuing with an ordinary Bash login shell")


@unittest.skipUnless(Path("/bin/bash").is_file(), "Linux Bash PTY required")
class LoginStartupContracts(unittest.TestCase):
    def probe(self, hook: str, *, enhanced: bool, debug: bool = False, profile_extra: str = "",
              force_bash: bool = False, shell: str = "/bin/bash", extra_env=None):
        directory = tempfile.TemporaryDirectory(prefix="atuin-ssh-profile-")
        self.addCleanup(directory.cleanup)
        profile = Path(directory.name) / ".bash_profile"
        profile.write_text(
            "PROFILE_COUNT=$(( ${PROFILE_COUNT:-0}+1 ))\n"
            "PROFILE_TOKEN=loaded\n"
            "HOOK_COUNT=0\n"
            "printf '\\n__PROFILE__%s\\n' \"$PROFILE_COUNT\"\n"
            "alias profile_alias='printf __ALIAS_OK__'\n"
            "profile_function() { printf __FUNCTION_OK__; }\n"
            "set -o noclobber\n"
            + ("DEBUG_COUNT=0; trap 'DEBUG_COUNT=$((DEBUG_COUNT+1))' DEBUG\n" if debug else "")
            + hook + "\n"
            + profile_extra + "\n"
            "PS1='__STARTUP_PROMPT__> '\n",
        )
        argv = (["/bin/sh", "-c", remote_command("a"*32, "b"*32, force_bash=force_bash)] if enhanced
                else ["/bin/bash", "--login", "-i"])
        client = PTYClient(argv, env={"HOME": directory.name, "SHELL": shell, "PROFILE_COUNT": "0",
                                     "PROMPT_COMMAND": ":", **(extra_env or {})})
        self.addCleanup(client.close)
        client.expect(b"\r\n__PROFILE__1\r\n")
        client.expect(PROMPT)
        client.send("printf '\\n__STATE__%s:%s:%s:%s__\\n' \"$PROFILE_COUNT\" \"$HOOK_COUNT\" \"${_AS_NONCE:+enhanced}\" \"$PROFILE_TOKEN\"\n")
        result = client.expect(STATE)
        client.expect(PROMPT)
        client.send("profile_alias; profile_function; [[ -o noclobber ]]; printf '\\n__OPTION__%s__\\n' \"$?\"\n")
        option = client.expect(b"\r\n__OPTION__0__\r\n")
        client.expect(PROMPT)
        self.assertIn(b"__ALIAS_OK____FUNCTION_OK__", option.string)
        self.assertEqual(client.transcript.count(b"\r\n__PROFILE__1\r\n"), 1)
        return client, tuple(value.decode() for value in result.groups())

    def test_scalar_prompt_command_append_preserves_startup_and_user_hook(self):
        hook = "PROMPT_COMMAND+=\"; ((HOOK_COUNT+=1))\""
        _, plain = self.probe(hook, enhanced=False)
        _, enhanced = self.probe(hook, enhanced=True)
        self.assertEqual(plain[0], enhanced[0], "profile must run exactly once")
        self.assertEqual(enhanced[0], "1")
        self.assertGreaterEqual(int(enhanced[1]), 1)
        self.assertEqual(enhanced[2:], ("enhanced", "loaded"))

    def test_array_prompt_command_append_preserves_user_hook(self):
        hook = "PROMPT_COMMAND=(\"${PROMPT_COMMAND-:}\" '((HOOK_COUNT+=1))')"
        _, plain = self.probe(hook, enhanced=False)
        _, enhanced = self.probe(hook, enhanced=True)
        self.assertEqual(plain[0], enhanced[0])
        self.assertGreaterEqual(int(enhanced[1]), 1)
        self.assertEqual(enhanced[2:], ("enhanced", "loaded"))

    def test_replaced_prompt_command_composes_integration_without_profile_damage(self):
        _, state = self.probe("PROMPT_COMMAND='((HOOK_COUNT+=1))'", enhanced=True)
        self.assertEqual(state[0], "1")
        self.assertGreaterEqual(int(state[1]), 1)
        self.assertEqual(state[2:], ("enhanced", "loaded"))

    def test_existing_debug_trap_is_preserved_when_capture_degrades(self):
        client, state = self.probe("PROMPT_COMMAND+=\"; ((HOOK_COUNT+=1))\"", enhanced=True, debug=True)
        self.assertEqual(state[2], "enhanced")
        client.send("trap -p DEBUG; printf '\\n__DEBUG_DONE__\\n'\n")
        result = client.expect(b"\r\n__DEBUG_DONE__\r\n")
        self.assertIn(b"DEBUG_COUNT=$((DEBUG_COUNT+1))", result.string)

    def test_profile_custom_readline_binding_remains_authoritative(self):
        client, state = self.probe("PROMPT_COMMAND+=\"; ((HOOK_COUNT+=1))\"", enhanced=True,
                                   profile_extra=r'''bind '"\C-r": "PROFILE_CUSTOM"' ''')
        self.assertEqual(state[2], "enhanced")
        client.send(b"\x12")
        result = client.expect(b"PROFILE_CUSTOM")
        self.assertNotIn(b"Atuin v", result.string)

    def test_non_bash_login_shell_reports_fixed_reason_and_keeps_plain_profile(self):
        directory = tempfile.TemporaryDirectory(prefix="atuin-ssh-plain-sh-")
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / ".profile").write_text(
            "PROFILE_COUNT=$(( ${PROFILE_COUNT:-0}+1 ))\n"
            "printf '\\n__PLAIN_SH_PROFILE__%s\\n' \"$PROFILE_COUNT\"\n"
            "plain_profile_function() { printf '__PLAIN_PROFILE_FUNCTION__'; }\n"
            "PS1='__PLAIN_SH_PROMPT__> '\n"
        )
        client = PTYClient(["/bin/sh", "-c", remote_command("a"*32, "b"*32)],
                           env={"HOME": directory.name, "SHELL": "/bin/sh", "PROFILE_COUNT": "0"})
        self.addCleanup(client.close)
        client.expect(NON_BASH_NOTICE)
        client.expect(b"\r\n__PLAIN_SH_PROFILE__1\r\n")
        client.expect(b"__PLAIN_SH_PROMPT__> ")
        client.send("plain_profile_function; printf '\\n__PLAIN_SH_STATE__%s:%s:%s__\\n' \"$PROFILE_COUNT\" \"${_AS_NONCE-}\" \"$-\"\n")
        result = client.expect(re.compile(rb"\r\n__PLAIN_SH_STATE__1::([^_]*)__\r\n"))
        self.assertIn(b"i", result[1])
        self.assertIn(b"__PLAIN_PROFILE_FUNCTION__", result.string)
        self.assertNotIn(b"atuin-ssh;1;", client.transcript)
        self.assertNotIn(directory.name.encode(), client.transcript)
        self.assertEqual(client.transcript.count(NON_BASH_NOTICE), 1)
        self.assertEqual(client.transcript.count(b"\r\n__PLAIN_SH_PROFILE__1\r\n"), 1)

    def test_explicit_bash_selection_enhances_without_changing_configured_shell(self):
        client, state = self.probe("PROMPT_COMMAND+=\"; ((HOOK_COUNT+=1))\"", enhanced=True,
                                   force_bash=True, shell="/bin/sh")
        self.assertEqual(state[2:], ("enhanced", "loaded"))
        client.send("shopt -q login_shell; printf '\\n__BASH_CHOICE__%s:%s__\\n' \"$SHELL\" \"$?\"\n")
        client.expect(b"\r\n__BASH_CHOICE__/bin/sh:0__\r\n")
        self.assertNotIn(NON_BASH_NOTICE, client.transcript)

    def legacy_client(self, **kwargs):
        binary = os.environ.get("ATUIN_SSH_TEST_BASH44")
        if not binary or not Path(binary).is_file():
            self.skipTest("set ATUIN_SSH_TEST_BASH44 to an actual Bash 4.4 binary")
        return self.initial_client(binary=binary, **kwargs)

    def initial_client(self, *, binary="/bin/bash", force_bash=False, date_script=None, prompt_hook=None):
        directory = tempfile.TemporaryDirectory(prefix="atuin-ssh-bash44-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "bin").mkdir()
        (root / "bin" / "bash").symlink_to(binary)
        if date_script is not None:
            clock = root / "bin" / "date"
            clock.write_text("#!/bin/sh\n" + date_script + "\n")
            clock.chmod(0o700)
        (root / ".bash_profile").write_text(
            "PROFILE_COUNT=$(( ${PROFILE_COUNT:-0}+1 ))\n"
            "printf '\\n__OLD_BASH_PROFILE__%s\\n' \"$PROFILE_COUNT\"\n"
            "HOOK_COUNT=0\n"
            + ("PROMPT_COMMAND=\"${PROMPT_COMMAND-:}; ((HOOK_COUNT+=1))\"\n" if prompt_hook is None
               else "PROMPT_COMMAND=" + shlex.quote(prompt_hook) + "\n")
            +
            "PS1='__OLD_BASH_PROMPT__> '\n"
        )
        client = PTYClient(["/bin/sh", "-c", remote_command("a"*32, "b"*32, force_bash=force_bash)],
                           env={"HOME": directory.name, "SHELL": "/bin/sh" if force_bash else str(root / "bin" / "bash"),
                                "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                                "PROFILE_COUNT": "0"})
        self.addCleanup(client.close)
        return client, directory.name

    def test_real_bash_4_reports_fixed_reason_before_plain_login(self):
        client, directory = self.legacy_client()
        client.expect(OLD_BASH_NOTICE)
        client.expect(b"\r\n__OLD_BASH_PROFILE__1\r\n")
        client.expect(b"__OLD_BASH_PROMPT__> ")
        client.send("printf '\\n__OLD_BASH_STATE__%s:%s:%s:%s__\\n' \"${BASH_VERSINFO[0]}\" \"$PROFILE_COUNT\" \"${_AS_NONCE-}\" \"$-\"\n")
        result = client.expect(re.compile(rb"\r\n__OLD_BASH_STATE__4:1::([^_]*)__\r\n"))
        self.assertIn(b"i", result[1])
        self.assertNotIn(b"atuin-ssh;1;", client.transcript)
        self.assertNotIn(directory.encode(), client.transcript)
        self.assertEqual(client.transcript.count(OLD_BASH_NOTICE), 1)

    def test_explicit_real_bash_4_has_prompt_ownership_and_capture(self):
        client, _ = self.legacy_client(force_bash=True)
        client.expect(b"\r\n__OLD_BASH_PROFILE__1\r\n")
        client.expect(b"__OLD_BASH_PROMPT__> ")
        # This must be the first user command, with no warm-up shell command.
        command = "printf '\\n__LEGACY_CAPTURED__\\n'; (exit 17)"
        client.send(command + "\n")
        client.expect(b"\r\n__LEGACY_CAPTURED__\r\n")
        client.expect(b"__OLD_BASH_PROMPT__> ")
        events = [value for value in FrameParser("a"*32).feed(bytes(client.transcript)) if isinstance(value, Frame)]
        hello = [event for event in events if event.kind == "HELLO"]
        self.assertEqual(len(hello), 1)
        self.assertEqual(hello[0].fields[3:], ("b"*32, "bash"))
        starts = [event for event in events if event.kind == "START" and event.fields[1] == command]
        self.assertEqual(len(starts), 1)
        completions = [event for event in events if event.kind == "END" and event.fields[0] == starts[0].fields[0]]
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0].fields[1], "17")
        self.assertRegex(starts[0].fields[-1], r"^[0-9]+\.[0-9]{1,9}$")
        self.assertRegex(completions[0].fields[-1], r"^[0-9]+\.[0-9]{1,9}$")
        self.assertNotIn(NON_BASH_NOTICE, client.transcript)
        self.assertNotIn(OLD_BASH_NOTICE, client.transcript)

    def test_explicit_real_bash_4_profile_readline_stays_plain_then_first_prompt_owns_widget(self):
        client, _ = self.legacy_client(force_bash=True,
            prompt_hook="IFS= read -e -r -p '__PROFILE_READ_E__> ' profile_input")
        self.assert_initial_widget_after_profile_readline(client)

    def test_default_first_prompt_owns_widget_after_profile_readline(self):
        client, _ = self.initial_client(
            prompt_hook="IFS= read -e -r -p '__PROFILE_READ_E__> ' profile_input")
        self.assert_initial_widget_after_profile_readline(client)

    def test_default_first_command_is_captured_after_appended_profile_hook(self):
        client, _ = self.initial_client()
        client.expect(b"__OLD_BASH_PROMPT__> ")
        command = "printf '\\n__DEFAULT_FIRST_CAPTURE__\\n'; (exit 19)"
        client.send(command + "\n")
        client.expect(b"\r\n__DEFAULT_FIRST_CAPTURE__\r\n")
        client.expect(b"__OLD_BASH_PROMPT__> ")
        events = [event for event in FrameParser("a"*32).feed(bytes(client.transcript)) if isinstance(event, Frame)]
        starts = [event for event in events if event.kind == "START" and event.fields[1] == command]
        self.assertEqual(len(starts), 1)
        self.assertTrue(any(event.kind == "END" and event.fields[:2] == (starts[0].fields[0], "19") for event in events))

    def assert_initial_widget_after_profile_readline(self, client):
        client.expect(b"__PROFILE_READ_E__> ")
        client.send(b"\x12abc")
        client.drain(.05)
        client.send(b"\x07\n")
        client.expect(b"__OLD_BASH_PROMPT__> ")
        before = [event for event in FrameParser("a"*32).feed(bytes(client.transcript)) if isinstance(event, Frame)]
        self.assertFalse(any(event.kind == "REQUEST" for event in before))
        client.send(b"\x12")
        client.expect(re.compile(rb";REQUEST;[^\x07]*\x07"))
        requests = [event for event in FrameParser("a"*32).feed(bytes(client.transcript))
                    if isinstance(event, Frame) and event.kind == "REQUEST"]
        self.assertEqual(len(requests), 1)
        request = requests[0].fields[0]
        client.send("!" + "a"*32 + ":" + request + ":FENCE\n")
        client.expect(re.compile(rb";HANDOVER;[^\x07]*\x07"))
        client.send(response("a"*32, request, "cancel"))
        client.expect(b"__OLD_BASH_PROMPT__> ")

    def test_explicit_real_bash_4_without_nanosecond_clock_keeps_plain_login(self):
        client, _ = self.legacy_client(force_bash=True, date_script="printf '%s\\n' '1700000000 %N'")
        client.expect(OLD_CLOCK_NOTICE)
        client.expect(b"\r\n__OLD_BASH_PROFILE__1\r\n")
        client.expect(b"__OLD_BASH_PROMPT__> ")
        client.send("printf '\\n__LEGACY_PLAIN__%s:%s__\\n' \"$PROFILE_COUNT\" \"${_AS_NONCE-}\"\n")
        client.expect(b"\r\n__LEGACY_PLAIN__1:__\r\n")
        self.assertNotIn(b"atuin-ssh;1;", client.transcript)

    def test_explicit_bash_restores_modes_env_and_inherited_errexit_before_profiles(self):
        hook = "PROMPT_COMMAND+=\"; ((HOOK_COUNT+=1))\""
        extra = {"ENV": "", "BASHOPTS": "inherit_errexit"}
        plain, _ = self.probe(hook, enhanced=False, shell="/bin/sh", extra_env=extra)
        enhanced, _ = self.probe(hook, enhanced=True, force_bash=True, shell="/bin/sh", extra_env=extra)
        results = []
        for client in (plain, enhanced):
            client.send("printf '\\n__MODES_BEGIN__\\n'; set +o; shopt -p; printf '\\n__MODES_END__%s:%s:%s__\\n' \"${ENV+x}\" \"$ENV\" \"${_AS_BOOT_FD-unset}\"\n")
            client.expect(b"\r\n__MODES_BEGIN__\r\n")
            found = client.expect(re.compile(rb"\r\n__MODES_END__([^\r]+)__\r\n"))
            results.append((found.string[:found.start()], found[1]))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1][1], b"x::unset")

    def test_startup_defaults_and_readline_settings_match_before_user_profile(self):
        for history in (None, "", "custom"):
            with self.subTest(exported_histfile=history), tempfile.TemporaryDirectory(prefix="atuin-startup-defaults-") as temporary:
                root = Path(temporary)
                (root / ".bash_profile").write_text(
                    "printf '\\n__DEFAULTS_BEGIN__\\n'\n"
                    "declare -p HISTFILE HISTSIZE HISTFILESIZE PS1 PS2 2>/dev/null\n"
                    "bind -v\n"
                    "printf '\\n__DEFAULTS_END__\\n'\n"
                    "PS1='__DEFAULTS_PROMPT__> '\n"
                )
                env = {"HOME": temporary, "SHELL": "/bin/bash"}
                if history is not None:
                    env["HISTFILE"] = "" if history == "" else str(root / "custom-history")
                outputs = []
                for enhanced in (False, True):
                    argv = (["/bin/sh", "-c", remote_command("a"*32, "b"*32)] if enhanced
                            else ["/bin/bash", "--login", "-i"])
                    client = PTYClient(argv, env=env)
                    try:
                        client.expect(b"\r\n__DEFAULTS_BEGIN__\r\n")
                        result = client.expect(b"\r\n__DEFAULTS_END__\r\n")
                        outputs.append(result.string[:result.start()])
                        client.expect(b"__DEFAULTS_PROMPT__> ")
                        client.send("exit\n")
                    finally:
                        client.close()
                self.assertEqual(outputs[0], outputs[1])
                if history is None:
                    self.assertIn(b'.bash_history"', outputs[1])
                    self.assertIn(b"declare -- HISTFILE=", outputs[1])

    def test_explicit_posix_bash_keeps_original_env_startup_without_enhancement(self):
        directory = tempfile.TemporaryDirectory(prefix="atuin-ssh-posix-")
        self.addCleanup(directory.cleanup)
        init = Path(directory.name) / "original-env"
        init.write_text("printf '\\n__ORIGINAL_ENV__\\n'; PS1='__POSIX_PROMPT__> '\n")
        client = PTYClient(["/bin/sh", "-c", remote_command("a"*32, "b"*32, force_bash=True)],
                           env={"HOME": directory.name, "SHELL": "/bin/sh", "POSIXLY_CORRECT": "1", "ENV": str(init)})
        self.addCleanup(client.close)
        client.expect(b"existing POSIX Bash startup is unsupported")
        client.expect(b"\r\n__ORIGINAL_ENV__\r\n")
        client.expect(b"__POSIX_PROMPT__> ")
        client.send("printf '\\n__POSIX_STATE__%s:%s__\\n' \"${_AS_NONCE-}\" \"$ENV\"\n")
        client.expect(("\r\n__POSIX_STATE__:" + str(init) + "__\r\n").encode())
        self.assertEqual(client.transcript.count(b"\r\n__ORIGINAL_ENV__\r\n"), 1)
        self.assertNotIn(b"atuin-ssh;1;", client.transcript)


if __name__ == "__main__":
    unittest.main()
