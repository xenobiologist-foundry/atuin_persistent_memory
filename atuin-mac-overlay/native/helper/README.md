# Mac native Atuin components

Built from Atuin 18.24.1, commit `c58d2e993d05be423315f6ae3739e9ab3e45eea5`,
with private Rust 1.95.0 and Cargo.lock. The official arm64 Atuin stays unchanged.

- `atuin-ssh-native` uses upstream client/common/domain APIs for native privacy,
  metadata-correct writes/import, collision checks and stable-ID reconciliation.
- `atuin-ssh-search` is the real upstream TUI with `patch_search.py`: ACCOUNT,
  host/account-qualified path/workspace, tagged results and inherited descriptors.

From the standalone project root, run `python3 packaging/build.py`. It verifies
`dependencies.lock`, copies this helper into pinned upstream source, applies
anchored patches and compiles with `--locked` and macOS deployment target 14.0.
No Linux Dockerfile or parent checkout is involved. Older-OS/Intel execution is
not established by this target setting.

The helper checks native version and history/record/metadata migration versions,
checksums and success flags before writable constructors. Incompatible state and
daemon mode are refused. All native writes use upstream APIs, without native
schema changes. An owner-only lock serializes bridge mutations. Stable-ID replay
honors tombstones and exact native records; uniqueness conflicts stay pending.
Native privacy precedes durable bridge command payloads.

Capture/import/selection accepts at most 256 KiB UTF-8, without truncation. Queries
over 64 KiB use an anonymous inherited socketpair; READY uses a pipe after first
results. No Linux memfd, `/proc` or typed-query disk file is used. Native SQLite
expression/pattern limits still constrain actual search.

Private result protocol 2 tags insertion `__atuin_insert__:` and acceptance
`__atuin_accept__:`; empty output cancels. Stripping one tag preserves commands
literally beginning with either prefix. Missing/incompatible native search fails
before result allocation. GLOBAL removes identity predicates; native shell
filtering is independent and shipped defaults use `[search] shells="all"`.

Remote suggestions use native UUID prefix search plus a bounded read-only exact
row lookup to retain trailing whitespace. No SQL history writes or replacement
search store is introduced. Identical-host/account historical isolation remains
unresolved; registered collision guards are conservative pending/refusal behavior.

Run `python3 packaging/check.py --baseline` for native storage/privacy/replay/
suggestion coverage and `python3 packaging/check.py` for local UI/package tests.
Use disposable state only. Full installed acceptance and remaining gaps are in
[STATUS.md](../../STATUS.md); descriptor/ownership contracts are in
[PROTOCOL.md](../../docs/PROTOCOL.md).
