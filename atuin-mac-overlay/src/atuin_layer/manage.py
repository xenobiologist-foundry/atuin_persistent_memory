"""Per-user relocatable install/upgrade/removal. State is never packaged/deleted."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile

NAMES = ("atuin-layer", "ssh-overlay", "atuin-ssh")
MARKER = "# Managed by AtuinMacOverlay: "


def wrapper(prefix, name):
    return "#!/bin/sh\n" + MARKER + str(prefix) + "\nexec " + shlex.quote(str(prefix / "bin" / name)) + ' "$@"\n'


def install(source, prefix, bin_dir):
    source, prefix, bin_dir = source.resolve(), prefix.expanduser().absolute(), bin_dir.expanduser().absolute()
    if prefix == source or prefix in source.parents or source in prefix.parents:
        raise ValueError("installation and source must be separate directories")
    if prefix.exists() and not (prefix / "installation.json").is_file():
        raise ValueError("refusing to replace an unmanaged directory")
    if not (source / "dependencies.lock").is_file() or not (source / "bin/atuin").is_file():
        raise ValueError("not a built application")
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        target = bin_dir / name
        if target.exists() and target.read_text() != wrapper(prefix, name):
            raise ValueError("refusing to overwrite an unrelated launcher")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".overlay-install-", dir=prefix.parent) as directory:
        staged = Path(directory) / "application"
        shutil.copytree(source, staged, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "installation.json"))
        (staged / "installation.json").write_text(json.dumps({"application": "AtuinMacOverlay", "bin_dir": str(bin_dir)}, indent=2)+"\n")
        previous = Path(directory) / "previous"
        if prefix.exists():
            prefix.rename(previous)
        try:
            staged.rename(prefix)
        except BaseException:
            if previous.exists():
                previous.rename(prefix)
            raise
    for name in NAMES:
        destination = bin_dir / name
        temporary = bin_dir / ("." + name + ".install")
        temporary.write_text(wrapper(prefix, name))
        temporary.chmod(0o755)
        temporary.replace(destination)
    print("Installed " + str(bin_dir / "atuin-layer"))
    print("History and configuration retained separately.")


def remove(prefix):
    prefix = prefix.expanduser().absolute()
    metadata = json.loads((prefix / "installation.json").read_text())
    if metadata.get("application") != "AtuinMacOverlay":
        raise ValueError("not a managed installation")
    bin_dir = Path(metadata["bin_dir"])
    for name in NAMES:
        target = bin_dir / name
        if target.is_file() and target.read_text() == wrapper(prefix, name):
            target.unlink()
    shutil.rmtree(prefix)
    print("Application removed. History and configuration retained.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("install", "remove"))
    p.add_argument("--prefix", type=Path, default=Path.home() / "Library/Application Support/AtuinMacOverlay/application")
    p.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    args = p.parse_args()
    source = Path(__file__).resolve().parents[2]
    state = Path(os.environ.get("ATUIN_LAYER_STATE", str(Path.home() / "Library/Application Support/AtuinMacOverlay")))
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "application.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.exit(1, "Close active layer shells/history operations before installation or removal.\n")
        try:
            if args.action == "install":
                install(source, args.prefix, args.bin_dir)
            else:
                remove(args.prefix)
        except (OSError, ValueError):
            p.exit(1, "Installation/removal refused; unrelated files and history are retained.\n")


if __name__ == "__main__":
    main()
