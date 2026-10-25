# Pinned native Atuin components

Built from Atuin 18.24.1, commit `c58d2e993d05be423315f6ae3739e9ab3e45eea5`,
with Rust 1.95.0 and the checked Cargo.lock. The official Atuin binary stays unchanged.

| Executable | Responsibility |
| --- | --- |
| `atuin-ssh-native` | JSON adapter using upstream client/common/domain APIs for privacy, metadata-correct capture/import, collision probes and stable-ID reconciliation |
| `atuin-ssh-search` | Real upstream TUI plus `patch_search.py`: ACCOUNT, qualified remote directory/workspace, explicit result tags and READY/query descriptors |

`Dockerfile` verifies pinned source SHA256, adds this helper to the upstream
workspace and builds with `--locked`; no host Rust installation is required.
Exact downloads and versions are in `config/build-pins.toml` and `Dockerfile`.
Dependency changes require renewed interface/migration compatibility checks.

## Storage contract

Before writable native constructors, the helper checks installed version and
all existing history/record/metadata migration versions, checksums and success
flags through read-only connections. Incompatible state is refused, never
downgraded. New empty state uses native initialization. Daemon mode is refused.
Writes use upstream Sqlite/HistoryStore APIs, without native schema changes.

Operations are `check`, `filter`, `probe`, `start`, `write`, `import`, `discard`.
Replies contain states/IDs, not command bodies. Native privacy runs before bridge
payload persistence. Unknown imported cwd/status/duration use native `unknown`/
`-1` conventions, with synthetic timestamps/session limits retained in provenance.

An owner-only lock serializes cooperating writers. Stable-ID reconciliation scans
native encrypted records, honors tombstones and reconstructs exact missing views;
it never deduplicates by command text. Uniqueness conflicts remain pending.
Recovery calls allow 120 s; ordinary calls 10 s. Million-record scans measured
11.2–18.1 s; see [benchmarks](../docs/BENCHMARKS.md).

Registered endpoint collisions for one hostname/account remain pending after
privacy checks, including a final pre-write check. A damaged provenance registry
also fails closed. Historical/imported/unregistered origin isolation is unresolved.
With `store_failed=false`, unknown live outcomes stay in bounded RAM until success;
unknown imported outcomes remain pending without command payload.

## Search and exact results

Capture/import/selection transport accepts at most 256 KiB UTF-8, without
truncation. Native SQLite expression/pattern limits still apply. Queries over
64 KiB use inherited Linux memfd; READY uses an inherited descriptor. These are
closed after use and do not persist typed queries.

Private `ATUIN_SSH_RESULT_PROTOCOL=2` tags insertion `__atuin_insert__:` and
acceptance `__atuin_accept__:`; empty output cancels. Strip exactly one tag to
preserve commands literally beginning with either prefix. Remote widgets require
the compatible extension and fail before result allocation if it is unavailable.
GLOBAL removes identity predicates; native shell filtering remains independent.

## Verification

```sh
docker build --target test --tag atuin-ssh:test .
docker run --rm --entrypoint python atuin-ssh:test -m unittest discover -s /opt/atuin-ssh/tests -p test_storage.py -v
```

Run from the repository root with disposable state. Full terminal acceptance is
recorded in [status](../docs/STATUS.md), separately from storage tests. The opt-in
`benchmark` feature adds `atuin-ssh-bench-seed` only to test images; it refuses
nonempty/production roots and seeds through native APIs, never raw SQL writes.
