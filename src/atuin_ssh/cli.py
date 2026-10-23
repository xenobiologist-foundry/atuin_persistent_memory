"""Installed console entry point. Linux PTY work runs inside the hub."""
from __future__ import annotations
import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib

from . import __version__


def _version(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        return (result.stdout or result.stderr).splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "unavailable"


def doctor():
    root = Path(os.environ.get("ATUIN_HOME", str(Path.home()/".local/share/atuin")))
    config = Path(os.environ.get("ATUIN_CONFIG_DIR", str(root))) / "config.toml"
    try:
        effective = tomllib.loads(config.read_text())
    except (OSError, ValueError):
        effective = {}
    disabled = {name: effective.get(name) is False and os.environ.get("ATUIN_"+name.upper(), "false").lower() == "false"
                for name in ("auto_sync", "update_check")}
    report = {
        "atuin_ssh": __version__, "python": platform.python_version(), "platform": platform.platform(),
        "architecture": platform.machine(), "bash": _version(["bash", "--version"]),
        "openssh": _version(["/usr/bin/ssh", "-V"]), "atuin": _version(["atuin", "--version"]),
        "state_root": str(root), "config": str(config),
        "bridge_state": os.environ.get("ATUIN_SSH_STATE_DIR", "/state/bridge"),
        "native_integration": bool(os.environ.get("ATUIN_SESSION")),
        "ssh_wrapper": os.environ.get("ATUIN_SSH_INITIALIZED") == "1",
        "tty": os.isatty(0), "term": os.environ.get("TERM", "unset"),
        "network_history_features_disabled": disabled,
        "daemon": {"configured": effective.get("daemon", {}).get("enabled", False), "owner": "disabled by default"},
        "scope": "ACCOUNT/HOST/SESSION/DIRECTORY/WORKSPACE/GLOBAL" if shutil.which("atuin-ssh-search") else "stock host fallback: exact account scope unavailable",
        "native_helper": bool(shutil.which("atuin-ssh-native")),
        "native_search": bool(shutil.which("atuin-ssh-search")),
        "identity_boundary": "connection aliases/effective endpoints retained separately; isolation of different machines with identical native hostnames is pending",
        "layout": "one local native store; local or LAN ingress selected by Compose bind address",
        "pending": "inspect bridge outbox status; no command text included",
    }
    try:
        from .history import status_directory
        report["pending"] = status_directory(report["bridge_state"])
    except (ImportError, AttributeError, OSError, sqlite3.Error):
        report["pending"] = {"available": False, "reason": "bridge metadata unavailable"}
    if report["native_helper"]:
        from .atuin import NativeAtuin, NativeError
        try:
            report["storage_compatibility"] = NativeAtuin().native("check", {})
        except NativeError:
            report["storage_compatibility"] = {"compatible": False}
    print(json.dumps(report, indent=2))
    return 0 if all(disabled.values()) and "18.24.1" in report["atuin"] else 1


def _history_progress():
    last_phase, last_output = None, 0.0

    def notify(value):
        nonlocal last_phase, last_output
        phase = value["phase"]
        now = time.monotonic()
        done = value.get("processed") == value.get("total")
        if phase == last_phase and now - last_output < 0.5 and not done:
            return
        if phase == "fetch":
            message = "Reading remote Bash history using SSH; authentication may be required."
        elif phase == "wait":
            message = "Waiting for the active history import to finish."
        else:
            label = {"privacy": "Checking privacy", "preflight": "Checking native history",
                     "write": "Writing native Atuin history"}[phase]
            message = f"{label}: {value['processed']}/{value['total']}"
            if phase == "write":
                message += f"; {value['imported']} entries confirmed in this run"
        print(message, file=sys.stderr, flush=True)
        last_phase, last_output = phase, now

    return notify


def _history_action(args):
    progress = _history_progress()
    if args.history_action == "retry":
        from .history import Outbox
        writer = Outbox()
        try:
            writer.retry_failed()
            ready = writer.barrier(timeout=max(0.1, min(60, args.timeout)))
            result = {"visible": ready, **writer.status()}
        finally:
            writer.close()
    elif args.history_action == "resume-imports":
        from .importing import ImportLedger
        result = ImportLedger().resume(progress=progress)
    else:
        from .importing import import_history
        result = import_history(args.target, dry_run=args.dry_run,
                                max_entries=args.max_entries, max_bytes=args.max_bytes,
                                after_ns=args.after_ns, before_ns=args.before_ns,
                                progress=progress)
    print(json.dumps(result, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="atuin-ssh")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("shell", choices=["bash"])
    connect = sub.add_parser("connect")
    connect.add_argument("--bash", action="store_true",
                         help="use the destination's existing Bash for this session, without changing its login shell")
    connect.add_argument("ssh_args", nargs=argparse.REMAINDER)
    sub.add_parser("doctor")
    history = sub.add_parser("history")
    hs = history.add_subparsers(dest="history_action", required=True)
    imp = hs.add_parser("import")
    imp.add_argument("--target", required=True)
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--max-entries", type=int, default=10000)
    imp.add_argument("--max-bytes", type=int, default=8*1024*1024)
    imp.add_argument("--after-ns", type=int)
    imp.add_argument("--before-ns", type=int)
    retry = hs.add_parser("retry")
    retry.add_argument("--timeout", type=float, default=10)
    hs.add_parser("resume-imports")
    args = parser.parse_args(argv)
    if args.action == "init":
        print(files("atuin_ssh").joinpath("bash/hub.bash").read_text())
        return 0
    if args.action == "doctor":
        return doctor()
    if args.action == "history":
        from .atuin import NativeError
        try:
            return _history_action(args)
        except KeyboardInterrupt:
            if args.history_action in {"import", "resume-imports"}:
                print("Import canceled. Completed writes are retained. Resume saved pending entries with "
                      "`atuin-ssh history resume-imports`.", file=sys.stderr, flush=True)
            return 130
        except NativeError as error:
            print(f"History operation failed: {error}. Saved pending entries are retained.", file=sys.stderr)
            return 1
        except ValueError:
            # UnicodeDecodeError can embed source bytes in its representation.
            print("History source is invalid or exceeds the requested bounds.", file=sys.stderr)
            return 2
        except (OSError, sqlite3.Error):
            print("History operation could not read or update its local state or SSH process.", file=sys.stderr)
            return 1
    if args.action == "connect":
        from .ssh import plan_invocation
        raw = args.ssh_args
        if raw[:1] == ["--"]:
            raw = raw[1:]
        plan = plan_invocation(raw, stdin_tty=os.isatty(0), stdout_tty=os.isatty(1))
        proxy = os.environ.get("ATUIN_PTY_PROXY_ACTIVE", "") not in {"", "0"}
        if not plan.enhanced or os.environ.get("ATUIN_SSH_PLAIN") == "1" or proxy:
            os.execv("/usr/bin/ssh", ["/usr/bin/ssh", *raw])
        from .relay import Relay
        outbox = None
        try:
            from .history import Outbox
            outbox = Outbox()
        except (ImportError, OSError, TypeError):
            pass
        try:
            return Relay(raw, outbox=outbox, connection=plan, force_bash=args.bash).run()
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    sys.exit(main())
