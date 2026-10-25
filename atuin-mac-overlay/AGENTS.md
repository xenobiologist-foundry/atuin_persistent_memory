# Atuin Mac Overlay

Read HANDOFF.md as the product contract. Work only in this folder. Parent Linux
code is reference material, never a runtime/build dependency. Baseline snapshot
and SHA256 provenance live in vendor/prototype-core; keep that snapshot unchanged.

Run the application natively on macOS. Use disposable histories and owned Linux
containers for SSH tests. Never read personal history or keys, change profiles,
touch existing Docker projects, or access the restricted LAN test server.

Build: `python3 packaging/build.py`. Test: `python3 packaging/check.py`.
Keep STATUS.md honest about passed, failed, fallback and unverified gates.
Do not claim a stage complete from a build alone. Keep official Atuin distinct
from patched native search. Preserve native record writes and privacy filters.

No remote zsh adapter, sync, telemetry, recursive remote enhancement, or GUI.
Install/remove keep history by default. No sub-agents are required.
