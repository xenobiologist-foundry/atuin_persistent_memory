from __future__ import annotations
import json
import os
from pathlib import Path
import pwd
import socket
import signal
import subprocess
import tempfile
import termios
import tomllib
import fcntl

_LEASES = []


def app_root():
    # Source has src/ here; the runtime has lib/. Both are self-contained.
    return Path(__file__).resolve().parents[2]


def configure():
    root = app_root()
    state = Path(os.environ.get("ATUIN_LAYER_STATE", str(
        Path.home() / "Library/Application Support/AtuinMacOverlay"))).expanduser().absolute()
    for name in ("atuin", "bridge", "config"):
        directory = state / name
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    lease = (state / "application.lock").open("a")
    fcntl.flock(lease, fcntl.LOCK_SH)
    _LEASES.append(lease)
    config = state / "config/config.toml"
    try:
        with config.open("x", encoding="utf-8") as stream:
            stream.write((root / "config/default.toml").read_text())
        config.chmod(0o600)
    except FileExistsError:
        pass
    effective = tomllib.loads(config.read_text())
    if effective.get("daemon", {}).get("enabled", False):
        raise ValueError("native daemon mode has not been verified")
    # Prevent inherited Atuin storage paths, capture proxy and network options
    # from attaching this installation to another active writer or account.
    preferences = {"ATUIN_NOBIND", "ATUIN_ENTER_ACCEPT", "ATUIN_EXIT_MODE", "ATUIN_KEYMAP_MODE",
                   "ATUIN_FILTER_MODE_SHELL_UP_KEY_BINDING", "ATUIN_SEARCH_MODE_SHELL_UP_KEY_BINDING",
                   "ATUIN_SEARCH_MODE", "ATUIN_HISTORY_FILTER", "ATUIN_CWD_FILTER", "ATUIN_STORE_FAILED",
                   "ATUIN_SECRETS_FILTER", "ATUIN_STYLE", "ATUIN_INLINE_HEIGHT"}
    for key in list(os.environ):
        if key.startswith("ATUIN_") and key not in preferences and not key.startswith(("ATUIN_LAYER_", "ATUIN_SSH_", "ATUIN_KEYMAP_CURSOR__")):
            del os.environ[key]
    os.environ.update(
        ATUIN_LAYER_ROOT=str(root), ATUIN_LAYER_STATE=str(state),
        ATUIN_HOME=str(state / "atuin"), ATUIN_CONFIG_DIR=str(state / "config"),
        ATUIN_SSH_STATE_DIR=str(state / "bridge"), ATUIN_AUTO_SYNC="false",
        ATUIN_UPDATE_CHECK="false", ATUIN_DAEMON__ENABLED="false",
        ATUIN_AI__ENABLED="false", ATUIN_PTY_PROXY__ENABLED="false",
        ATUIN_HOST_NAME=socket.gethostname(), ATUIN_HOST_USER=pwd.getpwuid(os.getuid()).pw_name,
        PATH=str(root / "bin") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
    )
    # Explicit paths also prevent a config edit from selecting a shared DB.
    for key, name in (("DB_PATH", "history.db"), ("RECORD_STORE_PATH", "records.db"),
                      ("KEY_PATH", "key"), ("META__DB_PATH", "meta.db")):
        os.environ["ATUIN_" + key] = str(state / "atuin" / name)
    return root, state


def launch(root):
    if not os.isatty(0) or not os.isatty(1):
        raise ValueError("atuin-layer needs an interactive terminal")
    from atuin_ssh.atuin import NativeAtuin
    NativeAtuin().native("check", {})
    # A nested ordinary zsh owns the existing terminal directly. No local relay
    # intercepts editing, foreground app input or shell job control.
    previous = termios.tcgetattr(0)
    env = os.environ.copy()
    original = env.get("ZDOTDIR", str(Path.home()))
    env["ATUIN_LAYER_USER_ZDOTDIR"] = original
    env["ATUIN_LAYER_ZDOTDIR_WAS_SET"] = "1" if "ZDOTDIR" in env else "0"
    env["ATUIN_LAYER_PYTHON"] = str(root / "python/bin/python3")
    env["ATUIN_LAYER_ENTRY"] = str(root / "lib/atuin_layer/entry.py")
    with tempfile.TemporaryDirectory(prefix="atuin-layer-zsh-") as temporary:
        startup = Path(temporary)
        for name in (".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout"):
            (startup / name).write_text((root / "shell/zsh" / name).read_text())
        env["ZDOTDIR"] = temporary
        env["ATUIN_LAYER_STARTUP"] = temporary
        handlers = {}
        process = None
        def terminate(signum, frame):
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGHUP)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        try:
            for signum in (signal.SIGTERM, signal.SIGHUP):
                handlers[signum] = signal.signal(signum, terminate)
            process = subprocess.Popen(["/bin/zsh", "-il"], env=env)
            code = process.wait()
            return code if code >= 0 else 128 - code
        finally:
            termios.tcsetattr(0, termios.TCSANOW, previous)
            for signum, handler in handlers.items():
                signal.signal(signum, handler)


def doctor(root, state):
    from atuin_ssh.atuin import NativeAtuin, NativeError
    from atuin_ssh.blesh import load_bundle, BundleError
    from atuin_ssh.history import status_directory
    import platform
    def version(name):
        try:
            p = subprocess.run([str(root / "bin" / name), "--version"], capture_output=True, text=True, timeout=5)
            return p.stdout.strip() if p.returncode == 0 else "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            return "unavailable"
    try:
        compatibility = NativeAtuin().native("check", {})
    except NativeError:
        compatibility = {"compatible": False}
    try:
        bundle = load_bundle()
        editor = {"valid": True, "bytes": bundle.size}
    except BundleError:
        editor = {"valid": False}
    report = {"version": "0.1.0", "macos": platform.mac_ver()[0], "architecture": platform.machine(),
              "private_python": platform.python_version(), "atuin": version("atuin"),
              "native_search": version("atuin-ssh-search"), "storage": compatibility,
              "state": str(state), "network_history_features": "disabled",
              "destination_editor": editor, "pending": status_directory(state / "bridge"),
              "limits": ["Identical hostname/account across different machines needs explicit collision resolution; exact native isolation is unverified.",
                         "Only this arm64 Mac has native acceptance; no Intel or older OS claim.",
                         "Recursive remote SSH and inner sudo/container/tmux capture are outside scope."]}
    print(json.dumps(report, indent=2))
    return 0 if compatibility.get("compatible") and editor["valid"] and "18.24.1" in report["atuin"] else 1
