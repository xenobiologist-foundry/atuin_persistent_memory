"""Check restored regular-file bytes and ownership without displaying state."""
import hashlib
import pathlib
import stat
import sys
import tarfile

archive_path, destination = sys.argv[1:]
root = pathlib.Path(destination)
checked = 0
with tarfile.open(archive_path, "r:gz") as archive:
    for member in archive:
        if not member.isfile():
            continue
        restored = root / member.name
        info = restored.stat()
        with archive.extractfile(member) as expected, restored.open("rb") as actual:
            expected_hash = hashlib.file_digest(expected, "sha256").digest()
            actual_hash = hashlib.file_digest(actual, "sha256").digest()
        if expected_hash != actual_hash or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (member.uid, member.gid, member.mode):
            raise SystemExit("Restore verification failed; hub remains stopped.")
        checked += 1
print(f"Restore verified: {checked} regular files, bytes and permissions match.")
