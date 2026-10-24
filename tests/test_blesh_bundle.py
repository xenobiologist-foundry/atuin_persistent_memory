"""Pinned editor distribution and real Bash bootstrap input ownership."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import tarfile
import tempfile
import unittest
from importlib.resources import files

from atuin_ssh.blesh import (BleshBundle, BundleError, MAX_ARCHIVE_BYTES,
                             UPSTREAM_COMMIT, UPSTREAM_RELEASE, UPSTREAM_SHA256,
                             load_bundle, validate_archive)
from pty_client import PTYClient


def fixture_archive(extra=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in ("ble.sh", "lib/core-complete.sh", "lib/_package.bash", "licenses/LICENSE.md"):
            member = tarfile.TarInfo(name)
            body = b"# inert editor bundle fixture\n"
            member.mode = 0o644
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
        if extra is not None:
            archive.addfile(extra)
    return output.getvalue()


class SessionBundleContracts(unittest.TestCase):
    def test_wire_roundtrip_bounds_and_pinned_manifest(self):
        payload = fixture_archive()
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "editor.tar"
            manifest = Path(directory) / "editor.json"
            archive.write_bytes(payload)
            metadata = dict(schema=1, format="ustar", size=len(payload), sha256=digest,
                            upstream_release=UPSTREAM_RELEASE, upstream_commit=UPSTREAM_COMMIT,
                            upstream_sha256=UPSTREAM_SHA256)
            manifest.write_text(json.dumps(metadata))
            bundle = load_bundle(archive, manifest)
            nonce = "a" * 32
            lines = list(bundle.lines(nonce))
            prefix = f"!{nonce}:BUNDLE:DATA:".encode()
            self.assertEqual(base64.b64decode(b"".join(line[len(prefix):].strip()
                                                       for line in lines[:-1]), validate=True), payload)
            self.assertLessEqual(max(map(len, lines)), 4143)
            self.assertEqual(lines[-1], f"!{nonce}:BUNDLE:END:{len(payload)}:{digest}\n".encode())
            archive.write_bytes(payload[:-1] + b"!")
            with self.assertRaises(BundleError):
                load_bundle(archive, manifest)
            metadata["size"] = MAX_ARCHIVE_BYTES + 1
            manifest.write_text(json.dumps(metadata))
            with self.assertRaises(BundleError):
                load_bundle(archive, manifest)

    def test_links_special_files_and_traversal_are_rejected(self):
        for name, kind in (("../outside", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                           ("shortcut", tarfile.SYMTYPE), ("pipe", tarfile.FIFOTYPE)):
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.type = kind
                member.mode = 0o644
                member.linkname = "outside"
                with self.assertRaises(BundleError):
                    validate_archive(fixture_archive(member))

    def shells(self):
        choices = ["/bin/bash"]
        legacy = os.environ.get("ATUIN_SSH_TEST_BASH44", "/usr/local/bin/bash44")
        if Path(legacy).is_file():
            choices.append(legacy)
        return choices

    def setup_session(self, shell, directory, *, short_timeout=False):
        payload = fixture_archive()
        bundle = BleshBundle(len(payload), hashlib.sha256(payload).hexdigest(), payload)
        nonce, session = "b" * 32, "c" * 32
        source = files("atuin_ssh").joinpath("bash/blesh_setup.bash").read_text()
        for key, value in {"NONCE": nonce, "SESSION": session, "BUNDLE_SIZE": str(bundle.size),
                           "BUNDLE_SHA256": bundle.sha256}.items():
            source = source.replace("@" + key + "@", value)
        if short_timeout:
            source = source.replace("-t 30", "-t .2").replace("-t 10", "-t .2")
        resource = Path(directory) / "setup.bash"
        resource.write_text(source)
        terminal = PTYClient([shell, "--noprofile", "--norc", "-i"],
                             env={"PS1": "__BUNDLE_PROMPT__> ", "TMPDIR": directory})
        self.addCleanup(terminal.close)
        terminal.expect(b"__BUNDLE_PROMPT__> ")
        terminal.send("_as_test_before=$(stty -g); source " + shlex.quote(str(resource))
                      + "; _as_test_after=$(stty -g); "
                        "printf '\\n__BUNDLE_RESULT__%s:%s__\\n' \"${_AS_BLE_DIR:+ready}\" \"$([[ $_as_test_before == $_as_test_after ]] && printf restored)\"\n")
        terminal.expect(re.compile(rb"\x1b\]777;atuin-ssh;1;" + nonce.encode()
                                   + rb";1;BUNDLE_REQUEST;" + session.encode().hex().encode() + rb"\x07"))
        return terminal, bundle, nonce, session

    def test_real_bash_preserves_binary_handover_verifies_extracts_and_cleans(self):
        for shell in self.shells():
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as directory:
                terminal, bundle, nonce, session = self.setup_session(shell, directory)
                pending = b"queued\x00\xff\n\r\x03"
                terminal.send(pending + f"!{nonce}:BUNDLE:FENCE\n".encode())
                found = terminal.expect(re.compile(rb"\x1b\]777;atuin-ssh;1;" + nonce.encode()
                                        + rb";2;BUNDLE_HANDOVER;([a-f0-9]+);([a-f0-9]*)\x07"))
                self.assertEqual(bytes.fromhex(found[1].decode()).decode(), session)
                self.assertEqual(bytes.fromhex(bytes.fromhex(found[2].decode()).decode()), pending)
                for line in bundle.lines(nonce):
                    terminal.send(line)
                terminal.expect(b"\r\n__BUNDLE_RESULT__ready:restored__\r\n")
                directories = list(Path(directory).glob("atuin-ssh-blesh.*"))
                self.assertEqual(len(directories), 1)
                self.assertEqual(directories[0].stat().st_mode & 0o777, 0o700)
                self.assertTrue((directories[0] / "tree/ble.sh").is_file())
                self.assertFalse((directories[0] / "bundle.tar").exists())
                terminal.send("_as_ble_cleanup; printf '\\n__BUNDLE_CLEANED__\\n'\n")
                terminal.expect(b"\r\n__BUNDLE_CLEANED__\r\n")
                self.assertFalse(directories[0].exists())

    def test_missing_fence_waits_for_ordered_abort_before_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal, _, nonce, _ = self.setup_session("/bin/bash", directory, short_timeout=True)
            terminal.expect(re.compile(rb"\x1b\]777;atuin-ssh;1;" + nonce.encode() + rb";2;BUNDLE_ABORT;[a-f0-9]+\x07"))
            self.assertNotIn(b"\r\n__BUNDLE_RESULT__", terminal.drain(.05))
            terminal.send(f"!{nonce}:BUNDLE:END:0:{'0' * 64}\n")
            terminal.expect(b"\r\n__BUNDLE_RESULT__:restored__\r\n")
            self.assertFalse(list(Path(directory).glob("atuin-ssh-blesh.*")))
