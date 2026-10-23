# Measured performance

Measurements ran in Linux containers on Docker Desktop, linux/amd64, Python
3.14.2, native Atuin 18.24.1, Intel Core i7-14700K and kernel
6.6.87.2-microsoft-standard-WSL2. Docker reported 28 CPUs and about 33.5 GB RAM.
The OS page cache was not flushed. These are observations on this machine,
not guarantees for another workstation, hub or network.

## Real two-hop relay comparison

`tests/benchmark_relay.py` sends a unique 32-byte ASCII payload to raw `cat` on
the destination and waits for its exact echo. Both paths traverse the actual
workstation SSH client and hub sshd. The baseline uses the hub's `/usr/bin/ssh`
with an explicit remote command; the enhanced path enters the instrumented
destination Bash and then executes raw `cat`. Authentication/startup and the
first 20 warm-up exchanges are excluded. Each path has 1,000 measured samples.

| Round-trip milliseconds | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| Plain onward OpenSSH | 0.387 | 0.689 | 0.746 |
| Enhanced relay | 0.447 | 0.889 | 0.948 |
| Difference of percentiles | 0.060 | 0.200 | 0.202 |

The p95 difference is about 0.20 ms for an additional round trip through the
PTY/relay path. This supports the local overhead target in this fixture. It
does not isolate one-way relay latency: the paths use separate SSH sessions,
and the plain path was sampled first. Host scheduling and other activity can
affect the difference. No artificial network delay was injected.

Raw results: [relay-differential.json](../artifacts/relay-differential.json).

## Native Atuin scaling, separate from SSH

`tests/benchmark_native_tui.py` starts the actual `atuin-ssh-search` native TUI
in a real PTY. Its private readiness descriptor is emitted after terminal
negotiation, the initial native query and the first complete results frame.
Each size has 20 fresh-process samples per action. Query/navigation actions
return a verified selection through Tab; their timing includes terminal
teardown, result-file output and process exit.

| Total native records | Empty-query first-results p95 | Prefilled-query first-results p95 | One query key + Tab/exit p95 | Up + Tab/exit p95 |
| ---: | ---: | ---: | ---: | ---: |
| 10,000 | 10.43 ms | 12.53 ms | 7.38 ms | 2.35 ms |
| 100,000 | 10.75 ms | 12.80 ms | 23.09 ms | 3.08 ms |
| 1,000,000 | 11.70 ms | 13.70 ms | 213.49 ms | 2.03 ms |

Typing the complete 12-character `needle-00001` query followed by Tab took
p95 41.67/121.03/949.59 ms respectively. This is a whole query burst, not one
keypress. The one-key probe narrows an existing query before insertion. The
one-key/navigation measurements are conservative upper bounds that include
exit costs; engine-only and key-to-visible-render costs are not isolated.
At one million records the query cost is a material scaling limit.

The synthetic dataset has 10,000 command spellings repeated across four hosts,
two accounts, 64 projects and 64 sessions. Native ACCOUNT scope for
`bench-host-1:bench-user-1` sees one quarter of the total rows. The test-only
seed binary uses upstream `Sqlite::save_bulk` and `HistoryStore::init_store`,
including native encrypted records. It never writes raw SQL into native
history tables. Actual native store verification passed at one million rows.
This does not prove full two-hop latency at these sizes, global-scope costs,
true cold-disk behavior or simultaneous widget scaling. The daemon is disabled.

Stable-ID recovery has a different cost: an installed adapter replay with
`reconcile=true` scanned/decrypted the one-million-record native store and
returned `committed`/`reconciled=true` without increasing the row count. One
isolated observation took 11.20 s; a repeat timed around the production Python
adapter took 18.07 s during concurrent verification. These are single samples,
not percentiles. Recovery uses a 120 s background deadline and is outside the
terminal byte path; the result does not establish bounded recovery on every
store or machine.

Raw p50/p95/p99 distributions: [native-tui-scaling.json](../artifacts/native-tui-scaling.json).

## Reproduce with disposable state

From PowerShell after building `atuin-ssh:test`, create a fresh benchmark volume
and seed each size. The seed program rejects nonempty roots and is absent from
the production image.

```powershell
docker volume create atuin-ssh-benchmark-example
foreach ($count in 10000, 100000, 1000000) {
    docker run --rm --network none --mount type=volume,source=atuin-ssh-benchmark-example,target=/bench -e ATUIN_SSH_BENCHMARK=1 -e "ATUIN_HOME=/bench/$count" -e "ATUIN_CONFIG_DIR=/bench/$count" -e ATUIN_SESSION=019a0000000070008000000000000001 --entrypoint /usr/local/bin/atuin-ssh-bench-seed atuin-ssh:test $count
}
$artifactDir = (Resolve-Path .\artifacts).Path
docker run --rm --network none --mount type=volume,source=atuin-ssh-benchmark-example,target=/bench --mount "type=bind,source=$artifactDir,target=/artifacts" --entrypoint python atuin-ssh:test tests/benchmark_native_tui.py --samples 20 --output /artifacts/native-tui-scaling.json
docker run --rm --network none --mount type=volume,source=atuin-ssh-benchmark-example,target=/bench --mount "type=bind,source=$artifactDir,target=/artifacts" --entrypoint python atuin-ssh:test tests/benchmark_native_tui.py --samples 20 --output /artifacts/native-tui-scaling.json --append-single-key
docker compose -f compose.test.yaml run --rm --volume "${artifactDir}:/artifacts" client python tests/benchmark_relay.py --samples 1000 --output /artifacts/relay-differential.json
```

The same Docker commands run on Linux with shell-appropriate path/environment
syntax. They require no native Windows Python or separately managed WSL distro.
Never attach production state as benchmark storage.

The installed protocol-2 image's small-history two-hop widget baseline is in
[widget-baseline.json](../artifacts/widget-baseline.json): 20 samples and 994
records, p50/p95/p99 21.98/27.21/29.49 ms to the native header and
6.64/8.25/9.20 ms from Tab to the independent remote Readline snapshot. This
includes both SSH transports and client-side terminal processing; the query
was already present in the authoritative remote buffer. The 50/150/300 ms
destination-delay tests verify type-ahead correctness rather than claiming
performance percentiles. Separate workstation/hub latency and true cold-cache
measurements remain outstanding.
