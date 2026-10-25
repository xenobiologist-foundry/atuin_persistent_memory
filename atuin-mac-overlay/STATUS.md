# Delivery status — 2026-10-25

The local -> remote -> local interaction is implemented and verified with the
installed native Mac package. **Full version-one acceptance remains incomplete**
at the explicit identity, observation and compatibility gates below.

Platform: macOS 26.5.2 (25F84), arm64, zsh 5.9, OpenSSH 10.2p1. Private Python
3.14.2; official Atuin 18.24.1; native compatibility components built with Rust
1.95.0. Compiler deployment target: macOS 14.0; older-OS execution and Intel
are not claimed.

## Shared-history search fix — 2026-10-25

An installed-app reproduction of the previous release with an imported Bash command confirmed
two independent filters: the local Ctrl-R wrapper explicitly forces ACCOUNT,
and pinned Atuin defaults `search.shells` to `auto` (current shell plus rows
without shell metadata). The Mac widget sets `ATUIN_SHELL=zsh`, so imported Bash
rows remain hidden even after switching the host scope to GLOBAL. Default Up
also limits results to SESSION; imported rows have unknown historical sessions.

Verified in disposable state, without reading personal history:

- Native global CLI search found the imported remote row.
- Setting `filter_mode="global"` alone did not override local Ctrl-R's ACCOUNT.
- Cycling the UI to GLOBAL with the default shell filter still hid the Bash row.
- `[search] shells="all"` plus cycling to GLOBAL inserted the exact imported
  command into the local editor.
- `shells="all"` plus top-level `filter_mode_shell_up_key_binding="global"`
  also inserted that exact row through Up.

The earlier global-retrieval acceptance assertion was insufficient: matching a
token and counting a local history row did not prove the exact remote command
was selected or executed successfully. Its global-retrieval claim is withdrawn.
The reproduction checks the actual ZLE buffer without executing the selected
command. Probe: ignored `.build/check-local-search-scope.py`.

Implemented the permanent fix: the local widget honors native `filter_mode`,
and shipped defaults are `filter_mode="global"` and `[search] shells="all"`.
Remote Ctrl-R and inline suggestions retain account scope; Up remains SESSION
by default. README documents `shells="all"`/`"auto"` and existing-config updates.
No native Atuin rebuild or history migration is required.

Five new native UI regression cases verify exact Unicode Bash import selection
in local zsh without cycling scope, the `auto` opt-out, an explicit host filter,
session-scoped Up and account-scoped inline suggestions. The remote integration
case now verifies both the exact selected command and successful local execution,
closing the earlier false-positive assertion. Source local/package run: 25
discovered, 20 passed and 5 remote cases explicitly skipped; the focused remote
case and configuration-seeding preservation/idempotence case passed separately.
Independent rebuild/package checks passed: 26 local/parser/scope/lifecycle cases
(21 passed, 5 explicit remote skips), plus 76 baseline cases (70 passed, 6 fixture
skips). Updated both the standard per-user installation and the Projects/tmp
acceptance installation. Active application configuration is GLOBAL/all shells,
with SESSION retained for Up. The prior config was backed up and only the two
requested settings changed; other settings and native history were retained.

Post-install checks against the actual standard per-user app passed all five
scope cases in 17.039 s and the strengthened real-SSH/global retrieval case in
20.244 s. README, default configuration and local widget match across workspace
source, standalone source, both release trees and both managed installations.

## Stage results

| Stage | Verified result |
| --- | --- |
| 1. Standalone | 52 selected baseline files with revision/SHA256 provenance. Independent native rebuild/package/tests in `/Users/vsfilaretov/Projects/tmp/source`, without parent imports, scripts or symlinks. |
| 2. Native foundation | Official arm64 Atuin plus separate helper/search. Darwin inherited READY/query descriptors and native posix_spawn PTY adapter. Real UI and terminal restoration tested. |
| 3. Local entry | Eleven native cases: first-command capture, search, suggestions, startup order, custom SSH/aliases/functions, existing Atuin/plugin composition, vi initialization, authoritative Unicode buffer/cursor/mark/keymap cancellation, concurrent IDs, privacy, failure status, parent exit status and restored terminal modes. |
| 4. Onward SSH | Actual Bash 5.2 and 4.4.23 with temporary ble.sh. Eight editor contracts passed on each: account suggestions, Right without execution, native insert/accept/cancel/Up, burst activation/query/Enter, completion, foreground read/password and cleanup. |
| 5. Shared memory/import | Native privacy/deletion/record integrity, zsh extended/multiline/metabyte parsing, dry-run/repeat/append, real remote HISTFILE import, stable-ID/batch recovery and coherent backup/restore passed. Local cross-shell global retrieval is fixed with exact-selection regressions above. Full identical-host/account isolation remains open. |
| 6. Compatibility | Installed remote Ctrl-Z/fg/Ctrl-C, resize, fullscreen less and disconnect recovery passed. Real OpenSSH ProxyJump command pass-through and preserving an owned ControlMaster passed. Broad authentication/forwarding/fault matrix remains open. |
| 7. Packaging | Relocatable private runtime, shell dependencies/licenses/build manifest, per-user install/upgrade/removal/doctor. Spaces/Unicode in installation/home/state paths tested. History retained; unrelated launchers refused. Runtime needs no Homebrew/system Python. Automatic Terminal launch deferred. |
| 8. Installed acceptance | Installed outside checkout in `Projects/tmp/acceptance/Installed Application 界`. Tests ran with PATH `/usr/bin:/bin`. Local/package, baseline, modern SSH and actual Bash 4.4 suites passed. Full v1 gates below remain open. |

## Installed evidence

| Run | Result |
| --- | --- |
| Local/parser/package lifecycle | 18 discovered; 15 passed, 3 remote cases skipped in the local-only run |
| Extracted regression suite | 76 discovered; 70 passed, 6 explicit fixture/platform skips |
| Modern local/remote/editor aggregate | 26 passed in 179.059 s |
| Additional installed SSH/terminal run | 5 passed in 45.903 s, including two new contracts |
| Installed actual Bash 4.4.23 editor suite | 8 passed in 111.509 s |

These runs overlap. The six baseline skips are two Bash-4.4+ receiver cases that
cannot use Mac Bash 3.2, three old Linux-hub transport cases and one dedicated
hub import case. Independent Mac SSH/import tests cover the one-hop architecture.
No old Linux aggregate is counted as Mac acceptance. Disposable logs stay in
ignored `.build` and `Projects/tmp/acceptance`; archives contain no transcripts.

## Runtime fixes

- Retained the disabled updater's executable mode to reproduce the exact pinned
  editor tar: 3,799,040 bytes, SHA256
  `63a0c475827efb41f8156a28b8e057749c28f03fc4cc9b5989e86b204ee945ee`.
- Replaced `/proc`/memfd and Python-after-fork paths on Darwin.
- Prevented version reporting from reading the enclosing repository's Git HEAD.
- Completed local native history end before the next prompt/search.
- Restored terminal state and stopped the local child on catchable launcher exit.
- Fixed default Up detection for Readline's equivalent `\M-` and `\e` spellings,
  preserving custom/unbound keys.
- Staged package builds instead of truncating mapped private executables. An
  earlier overlapping build killed disposable test processes; stable reruns passed.

## Open gates and fallbacks

- Different endpoints reporting the same hostname/account: registered conflicts
  hold capture pending and refuse exact search. Historical, imported and
  unregistered rows lack complete machine isolation. No fake hostname or
  metadata-only mapping is claimed as a solution.
- macOS egress observation remains incomplete. Config/enforced env disable sync,
  update checks, AI, daemon and local PTY proxy; that is configuration evidence,
  not a zero-egress measurement. Remote editor egress is also unobserved.
- Broad authentication/MFA/agent/port forwarding, backpressure and complete
  malformed/stale-frame/disconnect fault injection need more installed execution.
  Protocol/storage bounds have regression coverage. Physical destinations,
  separate startup/UI/suggestion latency and arbitrary plugin combinations remain
  unverified. Personal histories/profiles were not inspected.
- OpenSSH 10.2 itself fails to quote a spaced `-F` path in its generated ProxyJump
  command. The app preserves argv; the jump test uses a plain temporary config.
  Direct `-F` and application/home/state paths with spaces are tested.
- Nonempty PROMPT_COMMAND, an existing editor or DEBUG/functrace conflicts keep
  GNU Readline fallback. No remote zsh, recursive SSH or inner-shell capture.
- Import alias/policy changes and ambiguous untimestamped rotations retain the
  handoff's deduplication limits. SIGKILL/exec/power loss can leave private remote
  session files or terminal modes.
- Local developer artifact: Intel, older OS and Apple signing/notarization are
  unverified. Automatic Terminal launch is an optional later convenience.

No personal histories/credentials/startup files or unrelated Docker resources
were used or changed. Only two owned loopback test destination containers were
created. Removal retains history and configuration by default.

## Run

```sh
/Users/vsfilaretov/Projects/tmp/acceptance/bin/atuin-layer doctor
/Users/vsfilaretov/Projects/tmp/acceptance/bin/atuin-layer
# In the enhanced local shell:
ssh-overlay your-existing-ssh-alias
```

Independent archive:
`/Users/vsfilaretov/Projects/tmp/source/dist/AtuinMacOverlay-arm64.tar.gz`.
See README.md for source builds, per-user installation and removal.
