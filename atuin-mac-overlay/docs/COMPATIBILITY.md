# Compatibility evidence

Development target: Apple Silicon arm64, macOS 26.5.2, zsh 5.9, OpenSSH 10.2p1.
Compiler deployment target is macOS 14.0; minimum-OS execution is unverified.

| Area | Evidence / boundary |
| --- | --- |
| Local entry | First-command capture, profile order, native UI, Unicode cancel, suggestions and concurrent IDs; local GLOBAL/all-shell default selects exact imported Bash entries without scope cycling |
| Profile composition | Disposable startup files, existing Atuin/autosuggestions, custom SSH/aliases/functions, vi initialization and binding-disable preference; arbitrary plugins unverified |
| Native store | Extracted storage/privacy/tombstone/batch/suggestion tests execute native Mac binaries |
| Bash 5.2 destination | Native Mac SSH -> temporary ble.sh -> Mac-native UI -> same remote editor; capture, burst insert, account-scoped remote search/suggestions, cleanup, then exact remote-command selection and successful execution in local zsh |
| GNU Readline | Explicit no-autosuggest, destination-only completion and foreground read input tested |
| Bash 4.4.23 | Eight editor contracts passed on the installed artifact, with configured /bin/sh account and explicit --bash |
| Remote import | Configured custom HISTFILE, dry-run, unchanged repeat through real OpenSSH PTY |
| Identity | Host/account and path scopes; registered endpoint collision guard retained; historic/unregistered collision isolation unresolved |
| SSH classification | Original argv/ssh -G regressions; installed ProxyJump command pass-through and owned ControlMaster retention; broader auth/forwarding matrix pending |
| Signals/jobs/fullscreen | Installed local restoration/parent status, remote Ctrl-Z/fg/Ctrl-C, resize, less and disconnect return passed; full fault matrix pending |
| Egress | Runtime configuration disables history networking; actual macOS observation remains a separate gate |
| Intel / older macOS | Not claimed |

The six extracted-test skips are explicit: Mac Bash 3.2 cannot exercise two
Bash-4.4+ receiver tests; three old transport cases require the Linux hub fixture;
one old installed-import case requires its dedicated hub fixture. Native Mac remote
tests supply independent coverage of the actual one-hop architecture. The old
Linux aggregate is not counted as Mac acceptance.

Readline can spell ESC as `\e` or `\M-`; both default bindings are recognized.
OpenSSH 10.2 does not quote a spaced `-F` path in its generated ProxyJump command;
use a supported config path for jumps. Install/home/state spaces and Unicode
have installed acceptance.
