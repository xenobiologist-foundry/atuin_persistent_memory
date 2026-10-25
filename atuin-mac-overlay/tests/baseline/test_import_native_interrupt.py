"""A real native prefix commit interrupted through the public import CLI."""
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from atuin_ssh.importing import ImportLedger


class DeferredLedger(ImportLedger):
    """Fixture: stage approved payloads, then let the public CLI own writes."""
    def resume(self, source_id=None, report=None, **kwargs):
        result = report if report is not None else {"imported": 0}
        result["pending"] = 70
        return result


@unittest.skipUnless(shutil.which("atuin-ssh-native") and shutil.which("atuin"),
                     "version-pinned native executables required")
class NativeImportInterruptContracts(unittest.TestCase):
    def test_cli_sigint_after_native_prefix_commit_reconciles_all_stable_ids(self):
        real_helper = shutil.which("atuin-ssh-native")
        with tempfile.TemporaryDirectory(prefix="atuin-ssh-import-interrupt-") as temporary:
            root = Path(temporary)
            native_root = root / "native"
            native_root.mkdir()
            (native_root / "config.toml").write_text("auto_sync=false\nupdate_check=false\n[daemon]\nenabled=false\n")
            bridge = root / "bridge"
            environment = {**os.environ, "ATUIN_HOME": str(native_root), "ATUIN_CONFIG_DIR": str(native_root),
                           "ATUIN_SSH_STATE_DIR": str(bridge), "ATUIN_AUTO_SYNC": "false", "ATUIN_UPDATE_CHECK": "false"}
            excluded = " excluded-interrupt-private-fixture"
            raw = "".join(f"#{1700000000 + index}\nprintf 'INTERRUPT_FIXTURE_{index:03}'\n" for index in range(70))
            raw += "#1700000070\n" + excluded + "\n"
            with patch.dict(os.environ, environment):
                ledger = DeferredLedger(bridge)
                report = ledger.import_bytes({"target": "fixture", "host": "interrupt-host", "user": "fixture-user",
                                              "histfile": "/fixture/history"}, raw.encode())
                self.assertEqual((report["imported"], report["pending"], report["filtered"]), (0, 70, 1))
                with ledger._db() as db:
                    identifiers = {row[0] for row in db.execute("SELECT id FROM occurrences")}
                    self.assertEqual(dict(db.execute("SELECT state,count(*) FROM occurrences GROUP BY state")), {"pending": 70})
                    self.assertEqual(db.execute("SELECT sum(attempts) FROM occurrences").fetchone()[0], 0)
                self.assertEqual(len(identifiers), 70)
                self.assertFalse(list(native_root.rglob("history.db")))
                for file in bridge.iterdir():
                    if file.is_file():
                        self.assertNotIn(excluded.encode(), file.read_bytes())

                marker = root / "prefix-committed.json"
                wrapper_dir = root / "wrapper"
                wrapper_dir.mkdir()
                wrapper = wrapper_dir / "atuin-ssh-native"
                wrapper.write_text(f"#!{sys.executable}\n" +
                    "import json,os,subprocess,sys,time\nfrom pathlib import Path\n" +
                    f"real={real_helper!r}\nmarker=Path({str(marker)!r})\n" +
                    "if sys.argv[1] != 'import_batch':\n    os.execv(real,[real,*sys.argv[1:]])\n" +
                    "request=json.load(sys.stdin)\n" +
                    "prefix=json.dumps({'events':request['events'][:3]},ensure_ascii=False).encode()\n" +
                    "completed=subprocess.run([real,'import_batch'],input=prefix,capture_output=True)\n" +
                    "if completed.returncode:\n    sys.stderr.buffer.write(completed.stderr)\n    sys.exit(completed.returncode)\n" +
                    "marker.write_text(json.dumps({'pid':os.getpid(),'submitted':len(request['events'])}))\n" +
                    "while True:\n    time.sleep(1)\n")
                wrapper.chmod(0o700)
                interrupted_env = {**environment, "PATH": str(wrapper_dir) + os.pathsep + environment["PATH"]}
                command = [sys.executable, "-m", "atuin_ssh.cli", "history", "resume-imports"]
                process = subprocess.Popen(command, env=interrupted_env, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    deadline = time.monotonic() + 15
                    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    if not marker.exists():
                        if process.poll() is None:
                            process.kill()
                        stdout, stderr = process.communicate(timeout=5)
                        self.fail("native prefix marker absent: " + repr((process.returncode, stdout, stderr)))
                    info = json.loads(marker.read_text())
                    self.assertEqual(info["submitted"], 64)
                    # Signal only the coordinator: subprocess.run must terminate
                    # its blocked helper and leave durable uncertain attempts.
                    process.send_signal(signal.SIGINT)
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 130, (stdout, stderr))
                    self.assertIn("Import canceled", stderr)
                    self.assertNotIn("Traceback", stderr)
                    # When this test itself is Docker PID1, a killed orphan can
                    # briefly remain as an adopted zombie. It must not remain
                    # running or hold any native/coordinator lock.
                    helper_status = Path(f"/proc/{info['pid']}/status")
                    deadline = time.monotonic() + 1
                    state = None
                    while helper_status.exists() and time.monotonic() < deadline:
                        try:
                            state = next(line.split()[1] for line in helper_status.read_text().splitlines()
                                         if line.startswith("State:"))
                        except FileNotFoundError:
                            state = None
                            break
                        if state == "Z":
                            break
                        time.sleep(.01)
                    self.assertTrue(not helper_status.exists() or state == "Z", "interrupted helper remained running")
                    try:
                        os.waitpid(info["pid"], os.WNOHANG)
                    except ChildProcessError:
                        pass
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)

                with ledger._db() as db:
                    self.assertEqual(dict(db.execute("SELECT state,count(*) FROM occurrences GROUP BY state")),
                                     {"pending": 6, "writing": 64})
                # The interrupted coordinator must release its private lock.
                with (bridge / "import-resume.lock").open("r+b") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                history = next(native_root.rglob("history.db"))
                with closing(sqlite3.connect(f"file:{history}?mode=ro", uri=True)) as db:
                    prefix_ids = {row[0] for row in db.execute("SELECT id FROM history")}
                self.assertEqual(len(prefix_ids), 3)
                self.assertTrue(prefix_ids <= identifiers)

                resumed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=120)
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                self.assertEqual(json.loads(resumed.stdout), {"imported": 70, "pending": 0})
                with ledger._db() as db:
                    self.assertEqual(dict(db.execute("SELECT state,count(*) FROM occurrences GROUP BY state")), {"committed": 70})
                with closing(sqlite3.connect(f"file:{history}?mode=ro", uri=True)) as db:
                    final_ids = {row[0] for row in db.execute("SELECT id FROM history")}
                self.assertEqual(final_ids, identifiers)
                # Read-only inspection of this pinned native fixture catches
                # duplicate Create records even if its materialized IDs agree.
                records = next(native_root.rglob("records.db"))
                with closing(sqlite3.connect(f"file:{records}?mode=ro", uri=True)) as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM store").fetchone()[0], 70)
                verified = subprocess.run(["atuin", "store", "verify"], env=environment,
                                          capture_output=True, text=True, timeout=15)
                self.assertEqual(verified.returncode, 0, verified.stderr)


if __name__ == "__main__":
    unittest.main()
