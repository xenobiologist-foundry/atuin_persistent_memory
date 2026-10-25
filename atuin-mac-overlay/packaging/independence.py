#!/usr/bin/env python3
"""Copy this source outside its checkout, then build/package/test there."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path)
    p.add_argument("--refresh", action="store_true", help="refresh an owned independent copy while retaining its own build cache")
    args = p.parse_args()
    parent = args.directory or Path(tempfile.mkdtemp(prefix="Atuin standalone é ", dir="/private/tmp"))
    target = parent / "source"
    if args.refresh and not (target / "dependencies.lock").is_file():
        p.error("--refresh needs an existing independent source copy")
    shutil.copytree(ROOT, target, dirs_exist_ok=args.refresh,
                    ignore=shutil.ignore_patterns(".build", "dist", "__pycache__", "*.pyc", ".git"))
    # Actual copied verified archives and registry; no symlink or parent path is
    # used by the independent build. Rust and native binaries rebuild there.
    cache = target / ".build"
    cache.mkdir(exist_ok=args.refresh)
    for name in ["downloads", "cargo-home"]:
        if not (cache / name).exists():
            shutil.copytree(ROOT / ".build" / name, cache / name, symlinks=False)
    print("Independent source: " + str(target), flush=True)
    log = parent / "build.log"
    with log.open("w") as stream:
        result = subprocess.run([sys.executable, target / "packaging/build.py"], cwd=target,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        print("Independent build failed; inspect " + str(log))
        return result.returncode
    for options in ([], ["--baseline"]):
        result = subprocess.run([sys.executable, target / "packaging/check.py", *options], cwd=target)
        if result.returncode:
            return result.returncode
    print("Independent build, package and native tests passed: " + str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
