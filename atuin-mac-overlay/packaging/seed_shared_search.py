#!/usr/bin/env python3
"""Explicitly seed the requested shared-history settings, preserving other config."""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", type=Path, required=True)
    p.add_argument("--state", type=Path, default=Path(os.environ.get("ATUIN_LAYER_STATE", str(
        Path.home() / "Library/Application Support/AtuinMacOverlay"))))
    args = p.parse_args()
    config = args.state / "config/config.toml"
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    original = config.read_bytes() if config.exists() else (args.app / "config/default.toml").read_bytes()
    try:
        before = tomllib.loads(original.decode())
    except (UnicodeError, tomllib.TOMLDecodeError):
        p.exit(1, "Invalid application configuration; no settings changed.\n")
    if "search" in before and not isinstance(before["search"], dict):
        p.exit(1, "Invalid search configuration; no settings changed.\n")
    expected = copy.deepcopy(before)
    expected["filter_mode"] = "global"
    expected.setdefault("search", {})["shells"] = "all"
    with tempfile.TemporaryDirectory(prefix=".shared-search-", dir=config.parent) as directory:
        staged = Path(directory) / "config.toml"
        staged.write_bytes(original)
        staged.chmod(0o600)
        env = dict(os.environ, ATUIN_CONFIG_DIR=directory, ATUIN_HOME=str(args.state / "atuin"),
                   ATUIN_AUTO_SYNC="false", ATUIN_UPDATE_CHECK="false", ATUIN_DAEMON__ENABLED="false",
                   ATUIN_AI__ENABLED="false", ATUIN_PTY_PROXY__ENABLED="false")
        for key, value in (("filter_mode", "global"), ("search.shells", "all")):
            result = subprocess.run([str(args.app / "bin/atuin"), "config", "set", key, value],
                                    env=env, capture_output=True, timeout=15)
            if result.returncode:
                p.exit(1, "Native configuration update refused; existing configuration retained.\n")
        updated = staged.read_bytes()
        if tomllib.loads(updated.decode()) != expected:
            p.exit(1, "Unexpected configuration change; existing configuration retained.\n")
        if config.exists() and config.read_bytes() != original:
            p.exit(1, "Configuration changed during seeding; retry with the new file.\n")
        if config.exists() and original != updated:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = config.with_name("config.toml.before-shared-search-" + stamp)
            shutil.copy2(config, backup)
            backup.chmod(0o600)
        staged.replace(config)
    print(json.dumps({"config": str(config), "filter_mode": "global", "search.shells": "all",
                      "other_settings_preserved": True}))


if __name__ == "__main__":
    main()
