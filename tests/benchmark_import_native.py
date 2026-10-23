"""Synthetic native import timing in a fresh profile; run inside Linux Docker.

docker run --rm --network none --entrypoint python atuin-ssh:test \
  /opt/atuin-ssh/tests/benchmark_import_native.py --batch

The default uses individual operations for comparison with an older installed
helper. Output is metadata only; no production state or destination is opened.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import uuid

from atuin_ssh.atuin import NativeAtuin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=200)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--helper", default="atuin-ssh-native")
    args = parser.parse_args()
    if not 1 <= args.entries <= 10_000:
        parser.error("entries must be between 1 and 10000")
    with tempfile.TemporaryDirectory(prefix="atuin-ssh-import-native-benchmark-") as temporary:
        root = Path(temporary)
        native_root = root / "native"
        native_root.mkdir(mode=0o700)
        os.environ.update(ATUIN_HOME=str(native_root), ATUIN_CONFIG_DIR=str(native_root),
                          ATUIN_SSH_STATE_DIR=str(root / "bridge"), ATUIN_SESSION="synthetic-benchmark")
        (native_root / "config.toml").write_text(
            "auto_sync=false\nupdate_check=false\nstore_failed=true\n[daemon]\nenabled=false\n"
        )
        adapter = NativeAtuin(helper=args.helper)
        now = time.time_ns()
        events = [{"id": uuid.uuid4().hex, "host": "synthetic-benchmark-host", "user": "synthetic-benchmark-user",
                   "cwd": "unknown", "session": "unknown", "shell": "bash",
                   "command": "printf IMPORT_BENCH_%06d" % index,
                   "timestamp_ns": str(now + index), "duration_ns": -1, "historical": True}
                  for index in range(args.entries)]
        report = {"entries": args.entries, "mode": "batch" if args.batch else "individual",
                  "state": "new isolated temporary profile; removed after verification"}
        total = time.monotonic()
        for operation in ("filter", "probe", "import"):
            start = time.monotonic()
            replies = (adapter.batch(operation, events) if args.batch else
                       [adapter.native(operation, event) for event in events])
            report[operation + "_seconds"] = round(time.monotonic() - start, 4)
            expected = (all(reply.get("allowed") for reply in replies) if operation == "filter" else
                        not any(reply.get("collision") for reply in replies) if operation == "probe" else
                        all(reply.get("state") == "committed" for reply in replies))
            if len(replies) != args.entries or not expected:
                raise RuntimeError("synthetic native benchmark refused entries")
        report["total_seconds"] = round(time.monotonic() - total, 4)
        with sqlite3.connect(native_root / "data/history.db") as connection:
            report["native_history_rows"] = connection.execute("SELECT count(*) FROM history").fetchone()[0]
        if report["native_history_rows"] != args.entries:
            raise RuntimeError("synthetic native history count mismatch")
        verified = subprocess.run(["atuin", "store", "verify"], capture_output=True, timeout=30)
        if verified.returncode:
            raise RuntimeError("synthetic native record verification failed")
        report["native_store_verify"] = True
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
