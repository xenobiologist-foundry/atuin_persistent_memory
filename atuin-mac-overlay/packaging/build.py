#!/usr/bin/env python3
"""Explicit source build. All archives are SHA256 pinned; runtime never downloads."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
LOCK = json.loads((ROOT / "dependencies.lock").read_text())


def run(argv, **kwargs):
    print("Building:", " ".join(map(str, argv[:5])), flush=True)
    subprocess.run(list(map(str, argv)), check=True, **kwargs)


def fetch(name):
    pin = LOCK["artifacts"][name]
    dest = BUILD / "downloads" / pin["file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        partial = dest.with_suffix(dest.suffix + ".partial")
        run(["/usr/bin/curl", "-fsSL", "--retry", "3", pin["url"], "-o", partial])
        if hashlib.sha256(partial.read_bytes()).hexdigest() != pin["sha256"]:
            raise RuntimeError(f"{name}: checksum mismatch")
        partial.replace(dest)
    if hashlib.sha256(dest.read_bytes()).hexdigest() != pin["sha256"]:
        raise RuntimeError(f"{name}: checksum mismatch")
    return dest


def unpack(name, directory, *, strip=False):
    archive = fetch(name)
    directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        # Upstream pinned archives can contain in-tree symlinks. Python's data
        # filter checks containment; remote session archives use stricter rules.
        stream.extractall(directory, filter="data")
    if strip:
        children = list(directory.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            raise RuntimeError("unexpected upstream archive layout")
        return children[0]
    return directory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-native", action="store_true", help="reuse already built native artifacts")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("this lock targets native Apple Silicon macOS; other targets need their own acceptance")
    packaged = ROOT / "dist/AtuinMacOverlay"
    BUILD.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="package-stage-", dir=BUILD))
    for sub in ["bin", "resources", "licenses", "lib"]:
        (output / sub).mkdir(parents=True, exist_ok=True)
    if args.skip_native:
        for name in ["atuin-ssh-native", "atuin-ssh-search"]:
            shutil.copy2(packaged / "bin" / name, output / "bin" / name)
        shutil.copy2(packaged / "licenses/Atuin-LICENSE", output / "licenses/Atuin-LICENSE")
    unpack("python", output)
    official = unpack("atuin", BUILD / "stock", strip=True)
    shutil.copy2(official / "atuin", output / "bin/atuin")
    if not args.skip_native:
        toolchain = BUILD / "toolchain"
        for name in ["rustc", "cargo", "rust-std"]:
            if not (toolchain / f".{name}-installed").exists():
                source = unpack(name, BUILD / name, strip=True)
                run(["/bin/sh", source / "install.sh", f"--prefix={toolchain}", "--disable-ldconfig"])
                (toolchain / f".{name}-installed").touch()
        upstream = BUILD / "upstream"
        if not upstream.exists():
            source = unpack("atuin-source", BUILD / "upstream-extract", strip=True)
            source.rename(upstream)
        shutil.copytree(ROOT / "native/helper", upstream / "crates/atuin-ssh-native", dirs_exist_ok=True)
        shutil.copy2(ROOT / "native/helper/Cargo.lock", upstream / "Cargo.lock")
        if not (upstream / ".overlay-patched").exists():
            run([sys.executable, ROOT / "native/helper/patch_search.py", upstream])
            (upstream / ".overlay-patched").touch()
        # Upstream otherwise walks into an enclosing unrelated Git checkout.
        # Source archives must identify the pinned upstream commit everywhere.
        build_rs = upstream / "crates/atuin/build.rs"
        deterministic = 'fn main() { println!("cargo:rustc-env=GIT_HASH=c58d2e993d05be423315f6ae3739e9ab3e45eea5"); }\n'
        if build_rs.read_text() != deterministic:
            build_rs.write_text(deterministic)
        env = dict(os.environ, PATH=str(toolchain / "bin") + os.pathsep + os.environ["PATH"],
                   CARGO_HOME=str(BUILD / "cargo-home"), MACOSX_DEPLOYMENT_TARGET=LOCK["deployment_target"],
                   CARGO_BUILD_JOBS="4")
        for package in ["atuin-ssh-native", "atuin"]:
            flags = [] if package == "atuin-ssh-native" else ["--no-default-features", "--features", "client"]
            run([toolchain / "bin/cargo", "build", "--release", "--locked", "-p", package, *flags], cwd=upstream, env=env)
        shutil.copy2(upstream / "target/release/atuin-ssh-native", output / "bin/atuin-ssh-native")
        shutil.copy2(upstream / "target/release/atuin", output / "bin/atuin-ssh-search")
        shutil.copy2(upstream / "LICENSE", output / "licenses/Atuin-LICENSE")
    run(["/usr/bin/cc", "-Wall", "-Wextra", "-Werror", "-mmacosx-version-min=" + LOCK["deployment_target"],
         ROOT / "native/pty_spawn.c", "-o", output / "bin/atuin-layer-pty"])
    plugin = unpack("zsh-autosuggestions", BUILD / "zsh-plugin", strip=True)
    shutil.copytree(plugin, output / "resources/zsh-autosuggestions", dirs_exist_ok=True)
    shutil.copy2(plugin / "LICENSE", output / "licenses/zsh-autosuggestions-LICENSE")
    editor = unpack("blesh", BUILD / "blesh", strip=True)
    shutil.copy2(ROOT / "vendor/prototype-core/docker/blesh-package.bash", editor / "lib/_package.bash")
    # Docker COPY replaces this existing executable without changing its mode.
    # Match those reviewed archive bytes on Darwin as well.
    (editor / "lib/_package.bash").chmod(0o755)
    (editor / "SOURCE").write_text("release=ble-nightly-20260908+d81fd54\ncommit=d81fd54feb0d996fdff20dca27eaf0201f7015cc\nsha256=7a2445f138e7f099dd5dee749391a8b045646d1b8a605975885be5b34b6b5f7e\n")
    recipe = (ROOT / "vendor/prototype-core/docker/build-blesh-bundle.py").read_text()
    recipe = recipe.replace('Path("/session-tree")', repr(editor)).replace('Path("/out")', repr(output / "resources"))
    # Execute the pinned deterministic recipe with only its absolute paths adapted.
    exec(compile(recipe, "build-blesh-bundle.py", "exec"), {"PosixPath": Path})
    manifest = json.loads((output / "resources/blesh-session.json").read_text())
    if manifest["sha256"] != "63a0c475827efb41f8156a28b8e057749c28f03fc4cc9b5989e86b204ee945ee":
        raise RuntimeError("remote editor bundle differs from pinned baseline")
    shutil.copytree(editor / "licenses", output / "licenses/blesh", dirs_exist_ok=True)
    shutil.copytree(ROOT / "src", output / "lib", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ["shell", "config", "docs"]:
        shutil.copytree(ROOT / name, output / name, dirs_exist_ok=True)
    for name in ["atuin-layer", "ssh-overlay", "atuin-ssh"]:
        shutil.copy2(ROOT / "packaging/launcher", output / "bin" / name)
        (output / "bin" / name).chmod(0o755)
    shutil.copy2(ROOT / "packaging/manage", output / "manage")
    (output / "manage").chmod(0o755)
    notices = []
    for package in sorted((BUILD / "cargo-home/registry/src").glob("*/*")):
        metadata = tomllib.loads((package / "Cargo.toml").read_text())["package"]
        texts = [p for p in package.iterdir() if p.is_file() and p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))]
        dest = output / "licenses/rust" / package.name
        dest.mkdir(parents=True, exist_ok=True)
        for text in texts:
            shutil.copy2(text, dest / text.name)
        notices.append({"name": metadata["name"], "version": metadata["version"],
                        "license": metadata.get("license", "see upstream"),
                        "repository": metadata.get("repository"), "texts": [p.name for p in texts]})
    (output / "licenses/rust-packages.json").write_text(json.dumps(notices, indent=2)+"\n")
    for name in ["dependencies.lock", "README.md", "STATUS.md"]:
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, output / name)
    provenance = {"schema": 1, "baseline": "0b577c0f8f55e9f0cc37c70b1a74bb466c7c9a72",
                  "upstream": "c58d2e993d05be423315f6ae3739e9ab3e45eea5",
                  "target": LOCK["target"], "deployment_target": LOCK["deployment_target"],
                  "files": {}}
    for file in sorted(output.rglob("*")):
        if file.is_symlink():
            if not file.resolve().is_relative_to(output.resolve()):
                raise RuntimeError("release symlink escapes its application")
        elif file.is_file() and file.name != "BUILD-MANIFEST.json" and "__pycache__" not in file.parts:
            provenance["files"][file.relative_to(output).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    (output / "BUILD-MANIFEST.json").write_text(json.dumps(provenance, indent=2)+"\n")
    # License texts embedded in the private Python distribution remain bundled.
    packaged.parent.mkdir(parents=True, exist_ok=True)
    if packaged.exists():
        # Never truncate a mapped private Python/native executable during a
        # rebuild. Keep the previous developer artifact under ignored .build.
        previous = Path(tempfile.mkdtemp(prefix="previous-package-", dir=BUILD)) / "application"
        packaged.rename(previous)
    output.rename(packaged)
    output = packaged
    archive = shutil.make_archive(str(ROOT / "dist/AtuinMacOverlay-arm64"), "gztar", output.parent, output.name)
    (ROOT / "dist/AtuinMacOverlay-arm64.tar.gz.sha256").write_text(hashlib.sha256(Path(archive).read_bytes()).hexdigest() + "\n")
    print(f"Built {output}")


if __name__ == "__main__":
    main()
