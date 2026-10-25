#!/usr/bin/env python3
"""Install and test the release outside the checkout, retaining test evidence."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--source", type=Path, default=ROOT / "dist/AtuinMacOverlay")
    p.add_argument("--legacy", action="store_true")
    args = p.parse_args()
    for source in (ROOT / "src").rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts:
            packaged = args.source / "lib" / source.relative_to(ROOT / "src")
            if not packaged.is_file() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(packaged.read_bytes()).digest():
                p.error("source artifact is stale; finish its build before installed acceptance")
    args.directory.mkdir(parents=True, exist_ok=True)
    prefix = args.directory / "Installed Application 界"
    env = dict(os.environ, ATUIN_LAYER_STATE=str(args.directory / "management-state"),
               ATUIN_LAYER_TEST_DOCKER=shutil.which("docker") or "/usr/local/bin/docker")
    subprocess.run([str(args.source / "manage"), "install", "--prefix", str(prefix),
                    "--bin-dir", str(args.directory / "bin")], env=env, check=True)
    env["PATH"] = "/usr/bin:/bin"
    suites = [("local-package", []), ("baseline", ["--baseline"]),
              ("remote-legacy" if args.legacy else "remote-modern", ["--legacy"] if args.legacy else ["--remote"])]
    reports = []
    for name, options in suites:
        log = args.directory / (name + ".log")
        with log.open("w") as stream:
            result = subprocess.run([sys.executable, str(ROOT / "packaging/check.py"), "--app", str(prefix), *options],
                                    env=env, cwd=args.directory, stdout=stream, stderr=subprocess.STDOUT)
        reports.append({"suite": name, "returncode": result.returncode, "log": str(log)})
        print(json.dumps(reports[-1]), flush=True)
    (args.directory / "results.json").write_text(json.dumps(reports, indent=2)+"\n")
    return int(any(report["returncode"] for report in reports))


if __name__ == "__main__":
    raise SystemExit(main())
