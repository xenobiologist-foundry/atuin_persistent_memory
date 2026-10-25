from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import sys
import tomllib

APP = Path(os.environ["ATUIN_LAYER_TEST_APP"])


class PackageLifecycle(unittest.TestCase):
    def test_shared_search_seed_preserves_custom_config_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="seed search 界 ") as temporary:
            state = Path(temporary)
            config = state / "config/config.toml"
            config.parent.mkdir()
            original = ('# Preserve this user comment.\nauto_sync=false\nupdate_check=false\n'
                        'filter_mode="host"\nfilter_mode_shell_up_key_binding="session"\n'
                        'inline_height=12\nhistory_filter=["fixture-private-pattern"]\n'
                        '[search]\nshells="auto"\n[daemon]\nenabled=false\n')
            config.write_text(original)
            script = Path(__file__).resolve().parents[1] / "packaging/seed_shared_search.py"
            for _ in range(2):
                result = subprocess.run([sys.executable, str(script), "--app", str(APP), "--state", str(state)],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
            expected = tomllib.loads(original)
            expected["filter_mode"] = "global"
            expected["search"]["shells"] = "all"
            self.assertEqual(tomllib.loads(config.read_text()), expected)
            self.assertIn("# Preserve this user comment.", config.read_text())
            backups = list(config.parent.glob("config.toml.before-shared-search-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)

    def test_install_upgrade_state_restore_and_removal_with_spaces_unicode(self):
        with tempfile.TemporaryDirectory(prefix="overlay install 界 ") as temporary:
            root = Path(temporary)
            prefix, bin_dir, state = root / "Application é", root / "User bin 界", root / "Data é"
            env = dict(os.environ, ATUIN_LAYER_STATE=str(state), PATH="/usr/bin:/bin", HOME=str(root))
            def run(arguments, ok=True):
                result = subprocess.run(list(map(str, arguments)), env=env, capture_output=True, text=True, timeout=60)
                if ok:
                    self.assertEqual(result.returncode, 0, result.stderr)
                return result
            install = [APP / "manage", "install", "--prefix", prefix, "--bin-dir", bin_dir]
            run(install)
            report = json.loads(run([bin_dir / "atuin-layer", "doctor"]).stdout)
            self.assertEqual(report["private_python"], "3.14.2")
            self.assertTrue(report["storage"]["compatible"])
            history = root / "history fixture"
            history.write_text(": 1700000000:0;echo PACKAGE_RESTORED_ONE\n: 1700000001:0;echo PACKAGE_RESTORED_ONE\n")
            env["ATUIN_LAYER_HISTFILE"] = str(history)
            imported = json.loads(run([bin_dir / "atuin-layer", "history", "import", "--local"]).stdout)
            self.assertEqual(imported["imported"], 2)
            run(install)
            self.assertEqual(json.loads(run([bin_dir / "atuin-layer", "history", "import", "--local"]).stdout)["duplicates"], 2)
            # All writers have exited. Preserve the entire native/bridge/config
            # tree, then restore at the same location with no cloned live writer.
            backup = root / "quiesced backup"
            shutil.copytree(state, backup)
            shutil.rmtree(state)
            shutil.copytree(backup, state)
            self.assertEqual(json.loads(run([bin_dir / "atuin-layer", "history", "import", "--local"]).stdout)["duplicates"], 2)
            with closing(sqlite3.connect(state / "atuin/history.db")) as database:
                self.assertEqual(database.execute("SELECT count(*) FROM history").fetchone()[0], 2)
            native_env = dict(env, PATH=str(prefix / "bin")+":/usr/bin:/bin", ATUIN_HOME=str(state / "atuin"),
                              ATUIN_CONFIG_DIR=str(state / "config"), ATUIN_DB_PATH=str(state / "atuin/history.db"),
                              ATUIN_RECORD_STORE_PATH=str(state / "atuin/records.db"), ATUIN_KEY_PATH=str(state / "atuin/key"))
            verified = subprocess.run([str(prefix / "bin/atuin"), "store", "verify"], env=native_env, capture_output=True, timeout=20)
            self.assertEqual(verified.returncode, 0)
            run([APP / "manage", "remove", "--prefix", prefix])
            self.assertFalse(prefix.exists())
            self.assertFalse((bin_dir / "atuin-layer").exists())
            self.assertTrue((state / "atuin/history.db").exists())

    def test_install_refuses_unrelated_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            target = bin_dir / "atuin-layer"
            target.write_text("unrelated fixture")
            result = subprocess.run([str(APP / "manage"), "install", "--prefix", str(root / "app"), "--bin-dir", str(bin_dir)],
                                    env=dict(os.environ, ATUIN_LAYER_STATE=str(root / "state")), capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(), "unrelated fixture")
