#!/usr/bin/env python3
"""Run meaningful unit/native-Mac tests with the packaged private Python."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", type=Path, default=ROOT / "dist/AtuinMacOverlay")
    p.add_argument("--remote", action="store_true")
    p.add_argument("--baseline", action="store_true")
    p.add_argument("--legacy", action="store_true")
    p.add_argument("--test", help="run one test module or case")
    args = p.parse_args()
    app = args.app.resolve()
    env = dict(os.environ, ATUIN_LAYER_TEST_APP=str(app), ATUIN_LAYER_ROOT=str(app),
               PATH=str(app / "bin") + os.pathsep + os.environ["PATH"])
    if args.remote:
        env["ATUIN_LAYER_TEST_REMOTE"] = "1"
    if args.legacy:
        env["ATUIN_LAYER_TEST_REMOTE"] = "1"
        env["ATUIN_LAYER_TEST_LEGACY"] = "1"
    if args.baseline:
        directory = ROOT / "tests/baseline"
        modules = ["test_ssh", "test_protocol", "test_relay", "test_context", "test_storage",
                   "test_import_batches", "test_native_batches", "test_native_suggestions",
                   "test_blesh_bundle", "test_pty_client", "test_import_transport"]
    else:
        directory = ROOT / "tests"
        modules = ["test_mac", "test_local_scope", "test_package"]
        if args.remote or args.legacy:
            modules.append("test_ble_mac")
    if args.test:
        modules = [args.test]
    code = ("import sys,unittest;sys.path[:0]=" + repr([str(app / "lib"), str(directory), str(ROOT / "tests/baseline")]) +
            ";suite=unittest.defaultTestLoader.loadTestsFromNames(" + repr(modules) +
            ");result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())")
    return subprocess.call([str(app / "python/bin/python3"), "-I", "-c", code], env=env, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
