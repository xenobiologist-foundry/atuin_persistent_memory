"""Observe hub editor startup and the disabled updater in a disposable image."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, "/opt/atuin-ssh/tests")
from pty_client import PTYClient


native = Path("/state/atuin")
native.mkdir(mode=0o700, parents=True, exist_ok=True)
shutil.copyfile("/usr/share/atuin-ssh/config.toml", native / "config.toml")
environment = dict(os.environ, ATUIN_HOME=str(native), ATUIN_CONFIG_DIR=str(native),
                   ATUIN_HOST_NAME="ble-privacy-hub", ATUIN_HOST_USER="root",
                   ATUIN_SESSION="ble-privacy-fixture")
seed = subprocess.check_output(["atuin", "history", "start", "--",
                                "printf BLE_PRIVACY_SUGGESTION"], env=environment).strip()
subprocess.run(["atuin", "history", "end", "--exit", "0", "--duration", "1000000",
                "--", seed.decode()], env=environment, check=True)
with tempfile.TemporaryDirectory(prefix="atuin-ssh-blesh-privacy-") as temporary:
    log = Path(temporary) / "network.trace"
    terminal = PTYClient(["strace", "-f", "-qq", "-e", "trace=network", "-o", str(log),
                          "bash", "--noprofile", "--norc", "-i"],
                         env=dict(environment, PS1="__BLE_PRIVACY__> "))
    try:
        terminal.expect(b"__BLE_PRIVACY__> ")
        terminal.send("source /etc/atuin-ssh/hub.bash; printf '\\n__BLE_READY__%s:%s__\\n' \"$BLE_VERSION\" \"$BLE_ATTACHED\"\n")
        terminal.expect(b"\r\n__BLE_READY__0.4.0-nightly+d81fd54:1__\r\n", timeout=30)
        terminal.drain(.5)
        for character in "printf BLE_PRIVACY_":
            terminal.send(character)
            terminal.drain(.03)
        terminal.expect(b"SUGGESTION", timeout=20)
        terminal.send(b"\x15")
        terminal.drain(.1)
        terminal.send("ble-update; printf '\\n__BLE_UPDATE__%s__\\n' \"$?\"\n")
        terminal.expect(b"ble.sh is pinned in this image; rebuild the image to update.")
        terminal.expect(b"\r\n__BLE_UPDATE__1__\r\n")
        terminal.send("exit\n")
        terminal.drain(.5)
    finally:
        terminal.close()
    attempts = [line for line in log.read_text().splitlines()
                if re.search(r"(?:connect|sendto|sendmsg|sendmmsg)\(.*AF_INET6?", line)]
    if attempts:
        raise RuntimeError("Attempted Internet network request observed")
    print(json.dumps({"cases": 3, "internet_connection_or_send_attempts": 0,
                      "updater_exit": 1, "network_namespace": "run with --network none",
                      "state": "disposable container only"}))
