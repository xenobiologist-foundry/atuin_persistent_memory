"""Existing prompt hooks must retain foreground input before any editor transfer."""
from pathlib import Path
import tempfile
import unittest

from atuin_ssh.blesh import BleshBundle
from atuin_ssh.bootstrap import remote_command
from pty_client import PTYClient


class RemotePromptFallback(unittest.TestCase):
    def test_custom_prompt_read_preserves_input_and_skips_bundle_transfer(self):
        # A small descriptor is sufficient: the preflight must never request
        # even one byte when the profile's actual prompt hooks are unsupported.
        bundle = BleshBundle(1, "0" * 64, b"x")
        for hook in ("PROMPT_COMMAND=_profile_hook", "PROMPT_COMMAND=(_profile_hook)"):
            with self.subTest(hook=hook), tempfile.TemporaryDirectory() as temporary:
                Path(temporary, ".bash_profile").write_text(
                    "_profile_once=0\n"
                    "_profile_hook() { if [[ $_profile_once == 0 ]]; then "
                    "_profile_once=1; IFS= read -e -r -p '__PROFILE_INPUT__> ' value; "
                    "printf '\\n__PROFILE_VALUE__%s__\\n' \"$value\"; fi; }\n"
                    + hook + "\nPS1='__FALLBACK_EDITOR__> '\n"
                )
                client = PTYClient(["/bin/sh", "-c", remote_command("a" * 32, "b" * 32, bundle=bundle)],
                                   env={"HOME": temporary, "SHELL": "/bin/bash"})
                try:
                    client.expect(b"__PROFILE_INPUT__> ", timeout=10)
                    client.send(b"profile-value\r")
                    client.expect(b"\r\n__PROFILE_VALUE__profile-value__\r\n", timeout=10)
                    client.expect(b"__FALLBACK_EDITOR__> ")
                    client.send("printf '\\n__EDITOR_MODE__%s:%s__\\n' \"${BLE_ATTACHED-unset}\" \"${_AS_NONCE:+native}\"\n")
                    client.expect(b"\r\n__EDITOR_MODE__unset:native__\r\n")
                    self.assertNotIn(b";BUNDLE_REQUEST;", client.transcript)
                    client.send("exit\n")
                finally:
                    client.close()
