"""Build on a native Linux filesystem, then copy installers to dist/linux.

The native build tree avoids mixing Windows/Linux npm and Cargo artifacts and
the DrvFS permissions/performance problems encountered when building in /mnt/c.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from prepare_linux_bundle import ROOT, prepare


def stage_workspace():
    identity = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    workspace = Path.home() / ".cache/factumdb" / identity
    workspace.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("node_modules", "target", "dist", "__pycache__", ".pytest_cache", ".venv", "venv", "*.pyc")
    for directory in ("frontend", "backend", "src-tauri"):
        target = workspace / directory
        # Refresh sources so deleted files cannot leak into later installers.
        # Preserve only generated dependency/build directories in this dedicated tree.
        if target.exists():
            target.resolve().relative_to((Path.home() / ".cache/factumdb").resolve())
            for child in target.iterdir():
                if child.name in {"node_modules", "target", "dist"}:
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        shutil.copytree(ROOT / directory, target, dirs_exist_ok=True,
                        ignore=lambda path, names: set(ignore(path, names)) | (
                            {"windows"} if Path(path).name == "runtime" else set()))
    for filename in ("package.json", "package-lock.json"):
        shutil.copy2(ROOT / filename, workspace / filename)
    return workspace


def build():
    if sys.platform != "linux":
        raise SystemExit("Run in Linux or WSL: python3 scripts/build_linux_bundle.py")
    # Prefer the isolated tools provisioned for this project's WSL build, when
    # present. Otherwise use the developer's normal Linux toolchain.
    local_tools = Path.home() / ".local/share/factumdb-build"
    for binary_dir in (local_tools / "node-v24.14.0-linux-x64/bin", local_tools / "rust/bin"):
        if binary_dir.is_dir():
            os.environ["PATH"] = str(binary_dir) + os.pathsep + os.environ["PATH"]
    for tool in ("node", "npm", "cargo", "rustc", "patchelf"):
        executable = shutil.which(tool)
        if not executable or executable.startswith("/mnt/"):
            raise SystemExit(f"Install a native Linux {tool} and add it to PATH before building.")
    if subprocess.check_output(["node", "-p", "process.platform"], text=True).strip() != "linux":
        raise SystemExit("The frontend must be built with Linux Node.js.")
    # WSL can expose many CPU cores while allowing only a few GiB of memory.
    # Bound concurrent Rust compilers; developers can override this explicitly.
    os.environ.setdefault("CARGO_BUILD_JOBS", "3")
    prepare()
    workspace = stage_workspace()
    for command in (["npm", "ci"], ["npm", "--prefix", "frontend", "ci"],
                    ["npm", "run", "tauri", "--", "build", "--bundles", "deb"]):
        subprocess.run(command, cwd=workspace, check=True)
    publish_packages(workspace)


def publish_packages(workspace):
    output = ROOT / "dist/linux"
    output.mkdir(parents=True, exist_ok=True)
    packages = list((workspace / "src-tauri/target/release/bundle/deb").glob("*.deb"))
    if not packages:
        raise RuntimeError("No Debian installer was produced")
    for package in packages:
        subprocess.run([sys.executable, str(ROOT / "scripts/check_linux_bundle.py"), str(package)], check=True)
        target = output / package.name
        shutil.copy2(package, target)
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        target.with_suffix(target.suffix + ".sha256").write_text(f"{checksum}  {target.name}\n")
        print(f"Installer: {target}", flush=True)
    print(f"Native build workspace: {workspace}", flush=True)


if __name__ == "__main__":
    build()
