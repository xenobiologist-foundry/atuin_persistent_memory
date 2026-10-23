"""Native Atuin costs at seeded scales, measured separately from SSH/relay RTT.

The readiness pipe is emitted after the native query and first complete frame.
Query/navigation timings include the requested native Tab insertion and exit;
they are conservative upper bounds, not isolated engine timings.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import select
import sqlite3
import subprocess
import sys
import tempfile
import time

from benchmark_pty import distribution
from pty_client import PTYClient


CONTEXT = {"ATUIN_HOST_NAME": "bench-host-1", "ATUIN_HOST_USER": "bench-user-1",
           "PWD": "/workspace/project-1/sub-1", "ATUIN_SESSION": "019a0000000070008000000000000001",
           "ATUIN_SHELL": "bash", "ATUIN_SSH_REMOTE_CONTEXT": "1", "ATUIN_WORKSPACES": "false",
           "ATUIN_AUTO_SYNC": "false", "ATUIN_UPDATE_CHECK": "false"}
EXPECTED = "rg --line-number 'needle-00001' /workspace/project-1"


def launch(profile: Path, query: str, keys: bytes) -> tuple[float, float, str]:
    fd, result_name = tempfile.mkstemp(prefix="atuin-native-benchmark-")
    os.close(fd)
    ready_read, ready_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    os.set_inheritable(ready_write, True)
    env = dict(os.environ)
    env.update(CONTEXT, ATUIN_HOME=str(profile), ATUIN_CONFIG_DIR=str(profile),
               ATUIN_QUERY=query, ATUIN_SSH_READY_FD=str(ready_write))
    started = time.monotonic()
    client = PTYClient(["/usr/local/bin/atuin-ssh-search", "search", "-i", "--filter-mode", "account",
                        "--keymap-mode", "emacs", "--result-file", result_name], env=env)
    os.close(ready_write)
    ready = bytearray()
    try:
        while ready != b"READY\n":
            if time.monotonic()-started > 30 or client.closed:
                raise AssertionError("native first-results readiness failed")
            client.read(.002)
            if select.select([ready_read], [], [], 0)[0]:
                ready.extend(os.read(ready_read, 1024))
        first_results_ms = (time.monotonic()-started)*1000
        if b"Atuin v18.24.1" not in client.transcript:
            raise AssertionError("native header absent from first results frame")
        action_start = time.monotonic()
        client.send(keys)
        while not client.closed:
            if time.monotonic()-action_start > 30:
                raise AssertionError("native action did not finish")
            client.read(.005)
        _, status = os.waitpid(client.pid, 0)
        if os.waitstatus_to_exitcode(status):
            raise AssertionError("native TUI exited unsuccessfully")
        action_ms = (time.monotonic()-action_start)*1000
        return first_results_ms, action_ms, Path(result_name).read_text()
    finally:
        os.close(ready_read)
        client.close()
        Path(result_name).unlink(missing_ok=True)


def benchmark(profile: Path, size: int, samples: int) -> dict:
    path = profile / "data/history.db"
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        count = db.execute("SELECT count(*) FROM history").fetchone()[0]
    if count != size:
        raise AssertionError(f"expected {size} records, found {count}")
    starts, query_actions, nav_starts, nav_actions = [], [], [], []
    _, _, first = launch(profile, "needle-", b"\t")
    for index in range(samples):
        start, duration, result = launch(profile, "", b"needle-00001\t")
        if result != EXPECTED:
            raise AssertionError("typed query selected the wrong native command")
        starts.append(start)
        query_actions.append(duration)
        start, duration, result = launch(profile, "needle-", b"\x1b[A\t")
        if result == first or not re.fullmatch(r"rg --line-number 'needle-[0-9]{5}' /workspace/project-[0-9]+", result):
            raise AssertionError("native Up did not select a different matching candidate")
        nav_starts.append(start)
        nav_actions.append(duration)
        print(f"native TUI {size} records: sample {index+1}/{samples}", file=sys.stderr, flush=True)
    return {"history_records": count,
            "empty_query_process_start_to_first_results_ms": distribution(starts),
            "typed_query_plus_tab_to_native_exit_ms": distribution(query_actions),
            "needle_query_process_start_to_first_results_ms": distribution(nav_starts),
            "up_navigation_plus_tab_to_native_exit_ms": distribution(nav_actions),
            "first_observed_empty_query_start_ms": starts[0],
            "cold_cache": "not established; OS page cache was not flushed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/bench")
    parser.add_argument("--sizes", nargs="+", type=int, default=[10_000, 100_000, 1_000_000])
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", required=True)
    parser.add_argument("--append-single-key", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.samples <= 1000:
        parser.error("samples must be in 1..1000")
    if args.append_single_key:
        result = json.loads(Path(args.output).read_text())
        for profile in result["profiles"]:
            durations = []
            for index in range(args.samples):
                _, duration, selected = launch(Path(args.root)/str(profile["history_records"]), "needle-000", b"0\t")
                if selected != EXPECTED:
                    raise AssertionError("single-key narrowed query selected the wrong native command")
                durations.append(duration)
            profile["single_query_key_plus_tab_to_native_exit_ms"] = distribution(durations)
            Path(args.output).write_text(json.dumps(result, indent=2)+"\n")
            print(f"verified single-key native query: {profile['history_records']} records, {args.samples} samples", file=sys.stderr)
        print(json.dumps(result, indent=2))
        sys.exit(0)
    result = {"kind": "isolated native Atuin PTY scaling, no SSH or relay", "python": platform.python_version(),
              "platform": platform.platform(), "cpu": next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), "unknown"),
              "version": subprocess.check_output(["/usr/local/bin/atuin-ssh-search", "--version"], text=True).strip(),
              "samples_per_size_per_action": args.samples, "profiles": [],
              "limits": ["First-results readiness is emitted after native negotiation, initial query and complete first frame.",
                         "Query and navigation timings include native Tab insertion, terminal teardown, result-file output and process exit; engine-only/key-to-visible latency is not isolated.",
                         "This measures native component costs only; it does not prove two-hop latency at these record counts.",
                         "The OS page cache was not flushed and a true cold-disk baseline is unverified."]}
    for size in args.sizes:
        result["profiles"].append(benchmark(Path(args.root)/str(size), size, args.samples))
        Path(args.output).write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
