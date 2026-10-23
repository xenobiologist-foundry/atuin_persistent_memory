"""Offline reproduction of a known identity limitation, not an isolation test.

Two fixture endpoints report the same canonical hostname/account. Their native
ACCOUNT search necessarily combines both origins; connection aliases alone do
not become a native history identity. No physical SSH hosts are simulated here.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from atuin_ssh.atuin import Context, NativeAtuin


def run():
    with tempfile.TemporaryDirectory(prefix="atuin-identity-gap-") as temporary:
        root = Path(temporary)
        (root / "config.toml").write_text(
            "auto_sync=false\nupdate_check=false\nsecrets_filter=true\n"
            "[daemon]\nenabled=false\n"
        )
        with patch.dict(os.environ, {"ATUIN_HOME": temporary,
                                    "ATUIN_CONFIG_DIR": temporary,
                                    "ATUIN_AUTO_SYNC": "false",
                                    "ATUIN_UPDATE_CHECK": "false"}):
            native = NativeAtuin()
            aliases = {"fixture-endpoint-a": "printf IDENTITY_ENDPOINT_A",
                       "fixture-endpoint-b": "printf IDENTITY_ENDPOINT_B"}
            for index, command in enumerate(aliases.values(), 1):
                event = {"id": f"00000000000040008000{index:012x}",
                         "host": "duplicate-reported-host", "user": "alice",
                         "cwd": "/remote/work",
                         "session": f"00000000000040008000{index:012x}",
                         "shell": "bash", "command": command,
                         "timestamp_ns": str(1700000000000000000 + index * 1000000000),
                         "status": 0, "duration_ns": 100000}
                assert native.native("write", event)["state"] == "committed"
            env = Context("duplicate-reported-host", "alice", "/remote/work",
                          "00000000000040008000000000000001").environment()
            env["ATUIN_SSH_REMOTE_CONTEXT"] = "1"
            found = subprocess.run(
                ["atuin-ssh-search", "search", "--filter-mode", "account", "--cmd-only"],
                env=env, check=True, capture_output=True, text=True, timeout=10)
            commands = set(found.stdout.splitlines())
            assert commands == set(aliases.values()), commands
            return {"result": "known identity gap reproduced",
                    "fixture_endpoint_labels": list(aliases),
                    "reported_origin": "duplicate-reported-host:alice",
                    "account_results": sorted(commands),
                    "limits": "Offline native representation probe; no physical SSH endpoint claim. Distinct aliases are not distinct native identities."}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
