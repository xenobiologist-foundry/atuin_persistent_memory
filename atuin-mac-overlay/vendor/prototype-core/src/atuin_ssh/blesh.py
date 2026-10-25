"""Read the pinned session editor bundle; never fetch destination dependencies."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
from collections.abc import Iterator


ARCHIVE_PATH = Path("/usr/share/atuin-ssh/blesh-session.tar")
MANIFEST_PATH = Path("/usr/share/atuin-ssh/blesh-session.json")
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 3072
UPSTREAM_RELEASE = "ble-nightly-20260908+d81fd54"
UPSTREAM_COMMIT = "d81fd54feb0d996fdff20dca27eaf0201f7015cc"
UPSTREAM_SHA256 = "7a2445f138e7f099dd5dee749391a8b045646d1b8a605975885be5b34b6b5f7e"


class BundleError(RuntimeError):
    """A missing, incompatible or corrupt packaged session editor."""


def _read_regular(path: Path, limit: int) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= limit:
                raise BundleError("Packaged session editor has an invalid file size or type.")
            content = stream.read(limit + 1)
            if len(content) != metadata.st_size:
                raise BundleError("Packaged session editor changed while reading.")
            return content
    except OSError:
        raise BundleError("Packaged session editor is unavailable.") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def validate_archive(payload: bytes) -> None:
    """Reject links, special files and unsafe names before any remote transfer."""
    if not 0 < len(payload) <= MAX_ARCHIVE_BYTES:
        raise BundleError("Packaged session editor exceeds its size bound.")
    required = {"ble.sh", "lib/core-complete.sh", "lib/_package.bash", "licenses/LICENSE.md"}
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            for member in archive:
                name = member.name
                parts = PurePosixPath(name).parts
                if (not re.fullmatch(r"[A-Za-z0-9._+@/-]+", name)
                        or name.startswith("/") or not parts or name != PurePosixPath(name).as_posix()
                        or any(part in (".", "..") for part in parts)
                        or name in seen or len(seen) >= 1024
                        or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE)
                        or member.pax_headers or member.mode & 0o7022):
                    raise BundleError("Packaged session editor contains an unsafe archive member.")
                if member.size < 0 or member.offset_data + member.size > len(payload):
                    raise BundleError("Packaged session editor archive is truncated.")
                total += member.size
                if total > MAX_ARCHIVE_BYTES:
                    raise BundleError("Packaged session editor exceeds its extracted size bound.")
                seen.add(name)
    except (tarfile.TarError, ValueError, UnicodeError):
        raise BundleError("Packaged session editor archive is invalid.") from None
    if not required <= seen:
        raise BundleError("Packaged session editor is missing required modules.")


@dataclass(frozen=True)
class BleshBundle:
    size: int
    sha256: str
    payload: bytes

    def lines(self, nonce: str) -> Iterator[bytes]:
        """Yield bounded ASCII protocol lines; callers retain bounded queues."""
        if not re.fullmatch(r"[a-f0-9]{32}", nonce):
            raise ValueError("invalid bundle nonce")
        prefix = f"!{nonce}:BUNDLE:DATA:".encode("ascii")
        for offset in range(0, self.size, CHUNK_BYTES):
            yield prefix + base64.b64encode(self.payload[offset:offset + CHUNK_BYTES]) + b"\n"
        yield f"!{nonce}:BUNDLE:END:{self.size}:{self.sha256}\n".encode("ascii")


def load_bundle(archive_path: Path = ARCHIVE_PATH,
                manifest_path: Path = MANIFEST_PATH) -> BleshBundle:
    """Validate fixed image artifacts before exposing any bundle bytes."""
    try:
        manifest = json.loads(_read_regular(Path(manifest_path), 16 * 1024))
    except (ValueError, UnicodeError):
        raise BundleError("Packaged session editor manifest is invalid.") from None
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1
            or manifest.get("format") != "ustar"
            or manifest.get("upstream_release") != UPSTREAM_RELEASE
            or manifest.get("upstream_commit") != UPSTREAM_COMMIT
            or manifest.get("upstream_sha256") != UPSTREAM_SHA256
            or type(manifest.get("size")) is not int
            or not 0 < manifest["size"] <= MAX_ARCHIVE_BYTES
            or not isinstance(manifest.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", manifest["sha256"])):
        raise BundleError("Packaged session editor manifest is incompatible.")
    payload = _read_regular(Path(archive_path), MAX_ARCHIVE_BYTES)
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != manifest["size"] or digest != manifest["sha256"]:
        raise BundleError("Packaged session editor checksum does not match its manifest.")
    validate_archive(payload)
    return BleshBundle(len(payload), digest, payload)
