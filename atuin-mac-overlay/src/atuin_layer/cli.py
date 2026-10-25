from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from .runtime import configure, launch, doctor


def parser():
    p = argparse.ArgumentParser(prog="atuin-layer")
    p.add_argument("--version", action="version", version="atuin-layer 0.1.0")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("doctor")
    h = sub.add_parser("history").add_subparsers(dest="history_action", required=True)
    imp = h.add_parser("import")
    source = imp.add_mutually_exclusive_group(required=True)
    source.add_argument("--local", action="store_true")
    source.add_argument("--target")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--max-entries", type=int, default=10000)
    imp.add_argument("--max-bytes", type=int, default=8*1024*1024)
    imp.add_argument("--after-ns", type=int)
    imp.add_argument("--before-ns", type=int)
    imp.add_argument("--ssh-config", type=Path, help="OpenSSH configuration for an explicit remote import")
    h.add_parser("resume-imports")
    local_suggest = sub.add_parser("suggest", help=argparse.SUPPRESS)
    local_suggest.add_argument("prefix")
    local_suggest.add_argument("session")
    local_suggest.add_argument("cwd")
    return p


def main(entry="atuin-layer", argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if entry == "atuin-ssh":
        if raw[:1] != ["connect"]:
            return main("atuin-layer", raw)
        raw = raw[1:]
        entry = "ssh-overlay"
    if entry == "ssh-overlay":
        root, state = configure()
        # Preserve the existing conservative OpenSSH classifier and argv parser.
        from atuin_ssh.cli import main as bridge_main
        return bridge_main(["connect", *raw])
    args = parser().parse_args(raw)
    try:
        root, state = configure()
        if args.action == "doctor":
            return doctor(root, state)
        if args.action == "suggest":
            from atuin_ssh.atuin import NativeAtuin, Context
            context = Context(os.environ["ATUIN_HOST_NAME"], os.environ["ATUIN_HOST_USER"], args.cwd, args.session, "zsh")
            sys.stdout.write(NativeAtuin().suggest(context, args.prefix))
            return 0
        if args.action == "history":
            from atuin_ssh.importing import ImportLedger, import_history
            from atuin_ssh.cli import _history_progress
            if args.history_action == "resume-imports":
                result = ImportLedger().resume(progress=_history_progress())
            else:
                if not 0 < args.max_bytes <= 64*1024*1024 or not 0 < args.max_entries <= 1000000:
                    raise ValueError("invalid import bounds")
                options = dict(dry_run=args.dry_run, max_entries=args.max_entries,
                               max_bytes=args.max_bytes, after_ns=args.after_ns,
                               before_ns=args.before_ns, progress=_history_progress())
                if args.local:
                    from .local_import import import_local
                    result = import_local(**options)
                else:
                    result = import_history(args.target, **options,
                                            ssh_options=["-F", str(args.ssh_config)] if args.ssh_config else None)
            print(json.dumps(result, indent=2))
            return 0
        return launch(root)
    except KeyboardInterrupt:
        print("Canceled. Saved pending imports require explicit history resume-imports.", file=sys.stderr)
        return 130
    except (OSError, ValueError, sqlite3.Error):
        print("atuin-layer: setup or history operation refused; run atuin-layer doctor. No command text is included in diagnostics.", file=sys.stderr)
        return 1
    except Exception as exc:
        from atuin_ssh.atuin import NativeError
        if not isinstance(exc, NativeError):
            raise
        print("atuin-layer: native compatibility check failed; writes were refused.", file=sys.stderr)
        return 1
