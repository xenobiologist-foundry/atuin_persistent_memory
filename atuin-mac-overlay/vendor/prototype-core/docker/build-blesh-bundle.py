"""Build a deterministic, portable session tar from the pinned editor tree."""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


source = Path("/session-tree")
target = Path("/out")
target.mkdir(parents=True, exist_ok=True)
provenance = dict(line.split("=", 1) for line in (source / "SOURCE").read_text().splitlines())
if provenance != {
    "release": "ble-nightly-20260908+d81fd54",
    "commit": "d81fd54feb0d996fdff20dca27eaf0201f7015cc",
    "sha256": "7a2445f138e7f099dd5dee749391a8b045646d1b8a605975885be5b34b6b5f7e",
}:
    raise RuntimeError("Session adapter requires the reviewed upstream editor pin")
archive_path = target / "blesh-session.tar"
entries = sorted(source.rglob("*"), key=lambda path: path.relative_to(source).as_posix())
if len(entries) > 1024:
    raise RuntimeError("Session bundle has too many entries")
with tarfile.open(archive_path, "w", format=tarfile.USTAR_FORMAT) as archive:
    for entry in entries:
        name = entry.relative_to(source).as_posix()
        if (not re.fullmatch(r"[A-Za-z0-9._+@/-]+", name)
                or entry.is_symlink() or not (entry.is_file() or entry.is_dir())):
            raise RuntimeError("Session bundle contains an unsupported entry")
        member = tarfile.TarInfo(name)
        member.mtime = 0
        member.uid = member.gid = 0
        member.uname = member.gname = ""
        if entry.is_dir():
            member.type = tarfile.DIRTYPE
            member.mode = 0o755
            archive.addfile(member)
        else:
            member.mode = 0o755 if entry.stat().st_mode & 0o111 else 0o644
            body = entry.read_bytes()
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
payload = archive_path.read_bytes()
if not 0 < len(payload) <= 8 * 1024 * 1024:
    raise RuntimeError("Session bundle exceeds its archive size bound")
manifest = {
    "schema": 1,
    "format": "ustar",
    "size": len(payload),
    "sha256": hashlib.sha256(payload).hexdigest(),
    "upstream_release": "ble-nightly-20260908+d81fd54",
    "upstream_commit": "d81fd54feb0d996fdff20dca27eaf0201f7015cc",
    "upstream_sha256": "7a2445f138e7f099dd5dee749391a8b045646d1b8a605975885be5b34b6b5f7e",
}
(target / "blesh-session.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
print(json.dumps({"session_bundle_bytes": manifest["size"], "sha256": manifest["sha256"]}))
