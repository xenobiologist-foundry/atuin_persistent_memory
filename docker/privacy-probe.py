"""Observe attempted Internet syscalls in disposable native Atuin operations."""
import json
import fcntl
import os
import pathlib
import pty
import re
import select
import subprocess
import struct
import tempfile
import time
import termios
import uuid


def trace(command, payload=None, interactive=False):
    global counter
    counter += 1
    log = root / f"network-{counter}.trace"
    invocation = ["strace", "-f", "-qq", "-e", "trace=network", "-o", str(log), *command]
    if interactive:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        process = subprocess.Popen(invocation, stdin=slave, stdout=slave, stderr=slave, env=environment)
        os.close(slave)
        started = time.monotonic()
        canceled = False
        try:
            while process.poll() is None and time.monotonic() - started < 10:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if b"\x1b[6n" in data:
                        os.write(master, b"\x1b[1;1R")
                if not canceled and time.monotonic() - started > 1:
                    os.write(master, b"\x1b")
                    canceled = True
            process.wait(timeout=3)
            if process.returncode not in (0, 130):
                raise RuntimeError("Native interactive search failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
        result = b""
    else:
        result = subprocess.check_output(invocation, input=payload, stderr=subprocess.PIPE, env=environment, timeout=20)
    attempts = [line for line in log.read_text().splitlines() if re.search(r"(?:connect|sendto|sendmsg|sendmmsg)\(.*AF_INET6?", line)]
    if attempts:
        raise RuntimeError("Attempted Internet network request observed")
    return result


with tempfile.TemporaryDirectory(prefix="atuin-ssh-privacy-") as temporary:
    root = pathlib.Path(temporary)
    native = root / "atuin"
    native.mkdir(mode=0o700)
    (native / "config.toml").write_text('auto_sync = false\nupdate_check = false\nenter_accept = true\ninline_height = 0\n[daemon]\nenabled = false\n[sync]\nrecords = true\n')
    environment = dict(os.environ, ATUIN_HOME=str(native), ATUIN_CONFIG_DIR=str(native), ATUIN_SESSION=uuid.uuid4().hex, ATUIN_HOST_NAME="privacy-destination", ATUIN_HOST_USER="remote", ATUIN_SHELL="bash", ATUIN_SSH_REMOTE_CONTEXT="1", PWD="/remote/probe", TERM="xterm-256color")
    counter = 0
    trace(["atuin", "--version"])
    trace(["atuin", "init", "bash", "--disable-ai"])
    started = trace(["atuin", "history", "start", "printf privacy-fixture"]).strip()
    trace(["atuin", "history", "end", "--exit", "0", "--duration", "1000000", started.decode()])
    trace(["atuin", "search", "--filter-mode", "global", "--limit", "1", "--format", ""])
    trace(["atuin-ssh-native", "check"])
    event = {"id": uuid.uuid4().hex, "host": "privacy-destination", "user": "remote", "cwd": "/remote/probe", "session": environment["ATUIN_SESSION"], "shell": "bash", "command": "printf native-privacy-fixture", "timestamp_ns": str(time.time_ns()), "status": 0, "duration_ns": 1000000}
    payload = json.dumps(event).encode()
    trace(["atuin-ssh-native", "filter"], payload)
    trace(["atuin-ssh-native", "start"], payload)
    trace(["atuin-ssh-native", "write"], payload)
    event.update(id=uuid.uuid4().hex, command="printf imported-privacy-fixture", timestamp_ns=str(time.time_ns()))
    trace(["atuin-ssh-native", "import"], json.dumps(event).encode())
    trace(["atuin-ssh-native", "check"])
    trace(["atuin-ssh-search", "search", "--filter-mode", "account", "--limit", "1", "--format", ""])
    trace(["atuin-ssh-search", "search", "--interactive", "--filter-mode", "account"], interactive=True)
    time.sleep(0.2)
    trace(["atuin-ssh-native", "check"])
    print(json.dumps({"cases": counter, "internet_connection_or_send_attempts": 0, "network_namespace": "run with --network none", "state": "isolated and removed"}))
