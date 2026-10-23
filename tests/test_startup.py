"""Login startup probes in isolated HOME directories, without fixture mutation.

These are real local Bash PTYs in Linux containers. They prove the bootstrap
startup surface independently; the two-hop suite separately establishes SSH.
"""

import os
from pathlib import Path
import re
import tempfile
import unittest

from atuin_ssh.bootstrap import remote_command
from pty_client import PTYClient


PROMPT = b"__STARTUP_PROMPT__> "
STATE = re.compile(rb"\r\n__STATE__([0-9]+):([0-9]+):([^:]*):([^:]+)__\r\n")


@unittest.skipUnless(Path("/bin/bash").is_file(), "Linux Bash PTY required")
class LoginStartupContracts(unittest.TestCase):
    def probe(self, hook: str, *, enhanced: bool, debug: bool = False, profile_extra: str = ""):
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
        argv = (["/bin/sh", "-c", remote_command("a"*32, "b"*32)] if enhanced
                else ["/bin/bash", "--login", "-i"])
        client = PTYClient(argv, env={"HOME": directory.name, "SHELL": "/bin/bash", "PROFILE_COUNT": "0",
                                     "PROMPT_COMMAND": ":"})
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

    def test_replaced_prompt_command_falls_back_without_profile_damage(self):
        _, state = self.probe("PROMPT_COMMAND='((HOOK_COUNT+=1))'", enhanced=True)
        self.assertEqual(state[0], "1")
        self.assertGreaterEqual(int(state[1]), 1)
        self.assertEqual(state[2:], ("", "loaded"))

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


if __name__ == "__main__":
    unittest.main()
