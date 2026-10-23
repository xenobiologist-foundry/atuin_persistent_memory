"""Small-history, two-hop wall-clock measurement; never a scaling claim."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import time

from test_two_hop import PROMPT, TwoHopNativeWidget


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    def percentile(q):
        return ordered[min(len(ordered)-1, max(0, round((len(ordered)-1)*q)))]
    return {"samples": len(values), "p50": statistics.median(values),
            "p95": percentile(.95), "p99": percentile(.99),
            "minimum": ordered[0], "maximum": ordered[-1]}


def run(samples: int) -> dict:
    if os.environ.get("ATUIN_SSH_E2E") != "1":
        raise RuntimeError("use disposable Compose client with ATUIN_SSH_E2E=1")
    TwoHopNativeWidget.setUpClass()
    case = TwoHopNativeWidget("test_cancel_preserves_unicode_buffer_cursor_and_mark")
    try:
        case.setUp()
        token, command = case.seed()
        opened, returned = [], []
        for _ in range(samples):
            case.client.send(token)
            case.client.drain(.025)
            opened.append(case.widget()*1000)
            before = time.monotonic()
            case.client.send(b"\t")
            case.client.expect(PROMPT)
            assert case.snapshot()[0] == command
            returned.append((time.monotonic()-before)*1000)
            case.client.send(b"\x01\x0b")
            case.client.drain(.025)
        db = Path("/test-state/atuin/data/history.db")
        count = None
        if db.is_file():
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
                count = connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), "unknown")
        return {
            "kind": "disposable local Docker two-hop baseline",
            "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "history_records": count, "python": platform.python_version(),
            "platform": platform.platform(), "cpu": cpu,
            "atuin": "18.24.1", "architecture": platform.machine(),
            "key_to_native_header_ms": distribution(opened),
            "tab_to_remote_readline_snapshot_ms": distribution(returned),
            "method": "Actual workstation OpenSSH PTY through hub sshd, installed bridge, destination sshd; monotonic wall clock; native CLI seeded record; unique query already typed in remote Readline before Ctrl-R; Tab followed by shell redraw and independent Readline snapshot.",
            "limits": ["Small disposable history only; no 10k/100k/1m scaling result.",
                       "Includes workstation-to-hub transport, destination ownership roundtrip, native UI startup/rendering and test client terminal processing.",
                       "Return includes result transport and a second remote Readline snapshot callback.",
                       "No artificial RTT was configured. The two network RTTs and local relay-only overhead are not isolated by this measurement.",
                       "Query/navigation p95, direct-OpenSSH differential and cold/warm storage/cache isolation remain unmeasured."],
        }
    finally:
        case.doCleanups()
        TwoHopNativeWidget.doClassCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output")
    args = parser.parse_args()
    if not 1 <= args.samples <= 1000:
        parser.error("samples must be in 1..1000")
    payload = json.dumps(run(args.samples), indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload)
    print(payload, end="")
