#!/usr/bin/env python3
"""Create only the disposable Compose fixture's test keypair."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1] / ".build/fixture-keys"
root.mkdir(parents=True, exist_ok=True, mode=0o700)
if not (root / "id_ed25519").exists():
    subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "id_ed25519")], check=True)
print("Disposable test keypair ready; no key contents printed.")
