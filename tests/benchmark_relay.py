"""Real two-hop raw-cat byte-echo comparison with plain hub OpenSSH.

The difference is an approximate added round trip, never an invented one-way
latency. Setup, authentication and the first 20 warm-up exchanges are excluded.
"""

import argparse
import json
from pathlib import Path
import time

from benchmark_pty import distribution
from test_two_hop import HUB_PROMPT, TwoHopNativeWidget


def sample_path(samples: int, plain: bool) -> dict:
    case = TwoHopNativeWidget("test_actual_remote_capture_is_immediately_native_searchable")
    try:
        case.setUp()
        command = "stty raw -echo; printf '__BYTEECHO_%s__' READY; exec cat"
        if plain:
            import shlex
            case.client.send("exit\n")
            case.client.expect(HUB_PROMPT)
            case.client.send("/usr/bin/ssh -tt remote@destination "+shlex.quote(command)+"\n")
        else:
            case.client.send(command+"\n")
        case.client.expect(b"__BYTEECHO_READY__")
        case.client.buffer.clear()
        timings = []
        for index in range(samples+20):
            payload = f"{index:08x}_".encode()+b"x"*23
            before = time.monotonic()
            case.client.send(payload)
            case.client.expect(payload)
            elapsed = (time.monotonic()-before)*1000
            if index >= 20:
                timings.append(elapsed)
        return distribution(timings)
    finally:
        case.doCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10000:
        parser.error("samples must be in 1..10000")
    TwoHopNativeWidget.setUpClass()
    try:
        plain = sample_path(args.samples, True)
        enhanced = sample_path(args.samples, False)
    finally:
        TwoHopNativeWidget.doClassCleanups()
    report = {"kind": "real workstation SSH -> hub -> destination raw-cat echo",
              "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "payload_bytes": 32, "warmup_samples_per_path": 20,
              "plain_system_ssh_roundtrip_ms": plain, "enhanced_relay_roundtrip_ms": enhanced,
              "p95_difference_ms": enhanced["p95"]-plain["p95"],
              "p50_difference_ms": enhanced["p50"]-plain["p50"],
              "method": "Same actual workstation/hub/destination OpenSSH paths and trusted keys; plain onward uses /usr/bin/ssh -tt with explicit raw-cat command; enhanced onward enters instrumented login Bash then execs cat. Monotonic wall clock around a unique 32-byte payload and its exact echo.",
              "limits": ["Difference is an approximate additional round-trip latency including PTY/relay and separate-session scheduling, not isolated one-way relay latency.",
                         "Plain path was sampled before enhanced path; host scheduling/cache/other test activity can affect differences.",
                         "No artificial transport RTT was added; this does not isolate workstation/hub versus hub/destination RTT.",
                         "Authentication/startup and 20 warm-up exchanges are excluded."]}
    Path(args.output).write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
