"""Stage pinned vendor resources. Requires Python on the BUILD machine only."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "scripts/windows-bundle.lock.json"
CACHE = ROOT / ".bundle-cache"
RESOURCES = ROOT / "src-tauri/resources"
RUNTIME = RESOURCES / "runtime/windows"


def digest(path, algorithm="sha256"):
    value = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fetch(item, record=False):
    path = CACHE / item["filename"]
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".download")
        subprocess.run(["curl.exe", "-f", "-L", "--retry", "3", item["url"], "-o", str(temporary)], check=True)
        temporary.replace(path)
    checksum = digest(path)
    if record:
        if "md5" in item and digest(path, "md5") != item["md5"]:
            raise ValueError(f"Vendor MD5 mismatch: {path.name}")
        item["sha256"] = checksum
    elif not item.get("sha256") or checksum != item["sha256"]:
        raise ValueError(f"SHA-256 mismatch or missing lock for {path.name}")
    return path


def extract(archive, target, include=lambda name: True, strip=0):
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.is_dir() or not include(info.filename):
                continue
            parts = Path(info.filename).parts[strip:]
            path = target.joinpath(*parts).resolve()
            path.relative_to(target.resolve())  # Reject archive traversal.
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as incoming, path.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def prepare(record=False):
    if sys.platform != "win32":
        raise SystemExit("This bundle targets Windows x64 only.")
    CACHE.mkdir(exist_ok=True)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    archives = {key: fetch(item, record) for key, item in lock.items() if isinstance(item, dict) and "url" in item}
    crt = Path(os.environ.get("FACTUMDB_VC_REDIST_DIR", r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT"))
    crt_files = sorted(crt.glob("*.dll"))
    if not crt_files:
        raise ValueError("Set FACTUMDB_VC_REDIST_DIR to the licensed Visual Studio x64 Microsoft.VC143.CRT redistributable directory.")
    crt_hashes = {p.name: digest(p) for p in crt_files}
    if record:
        lock["vc_runtime"] = {"version": "14.44.35112", "files": crt_hashes}
        LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    elif crt_hashes != lock["vc_runtime"]["files"]:
        raise ValueError("Visual C++ redistributable DLL hashes differ from the pinned bundle.")
    if RUNTIME.exists():
        # Only remove generated resources, never an arbitrary caller path.
        RUNTIME.resolve().relative_to(RESOURCES.resolve())
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    extract(archives["python"], RUNTIME / "python")
    # Python's isolated runtime ignores PYTHONPATH. Backend startup inserts its
    # resource path explicitly; ibd2sql needs its package in this fixed search path.
    (RUNTIME / "python/python313._pth").write_text("python313.zip\n.\n../ibd2sql\n", encoding="utf-8")
    extract(archives["ibd2sql"], RUNTIME / "ibd2sql", strip=1)
    prefix = f"mysql-{lock['mysql']['version']}-winx64/"
    extract(archives["mysql"], RUNTIME / "mysql", strip=1, include=lambda name:
            name.startswith(prefix + "bin/") and ((name.lower().endswith(".dll") and "-debug" not in name) or Path(name).name in
                {"innochecksum.exe", "ibd2sdi.exe", "mysqlbinlog.exe"})
            or name in {prefix + "LICENSE", prefix + "README", prefix + "docs/INFO_BIN", prefix + "docs/INFO_SRC"})
    for path in crt_files:
        shutil.copy2(path, RUNTIME / "mysql/bin" / path.name)
    (RUNTIME / "THIRD-PARTY-NOTICES.txt").write_text(
        "FactumDB Windows x64 bundled utilities\n\n"
        f"Python {lock['python']['version']}: https://www.python.org/ (python/LICENSE.txt).\n"
        f"MySQL Community {lock['mysql']['version']}: https://www.mysql.com/ (mysql/LICENSE).\n"
        "MySQL corresponding source and build instructions: ../../sources/mysql-8.4.11.tar.gz.\n"
        f"ibd2sql revision {lock['ibd2sql']['version']}: https://github.com/ddcw/ibd2sql (ibd2sql/LICENSE).\n"
        "Complete ibd2sql source: ibd2sql/ and ../../sources/ibd2sql-e6e8c380.zip.\n"
        "Microsoft Visual C++ runtime 14.44.35112: Copyright Microsoft Corporation.\n"
        "Redistributed app-local from the Visual Studio Build Tools licensed REDIST directory.\n"
        "https://visualstudio.microsoft.com/license-terms/vs2022-ga-diagnosticbuildtools/\n"
        "Pinned download and runtime SHA-256 hashes are in manifest.json.\n",
        encoding="utf-8")
    sources = RESOURCES / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    for name in ("mysql_source", "ibd2sql"):
        shutil.copy2(archives[name], sources / archives[name].name)
    tools = {
        "python_path": "python/python.exe",
        "innochecksum_path": "mysql/bin/innochecksum.exe",
        "ibd2sdi_path": "mysql/bin/ibd2sdi.exe",
        "mysqlbinlog_path": "mysql/bin/mysqlbinlog.exe",
        "ibd2sql_path": "ibd2sql/main.py",
    }
    for relative in tools.values():
        if not (RUNTIME / relative).is_file():
            raise ValueError(f"Required bundled file absent: {relative}")
    manifest = {"target": lock["target"], "tools": tools, "artifacts": lock,
                "files": {p.relative_to(RUNTIME).as_posix(): digest(p) for p in RUNTIME.rglob("*")
                          if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts}}
    (RUNTIME / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged Windows runtime: {RUNTIME}")
    for name, args in [
        ("Python", [str(RUNTIME / tools["python_path"]), "--version"]),
        ("innochecksum", [str(RUNTIME / tools["innochecksum_path"]), "--version"]),
        ("ibd2sdi", [str(RUNTIME / tools["ibd2sdi_path"]), "--version"]),
        ("mysqlbinlog", [str(RUNTIME / tools["mysqlbinlog_path"]), "--version"]),
        ("ibd2sql", [str(RUNTIME / tools["python_path"]), "-B", str(RUNTIME / tools["ibd2sql_path"]), "--version"]),
    ]:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"{name} failed to start ({result.returncode}): {result.stderr}")
        print(f"{name}: {result.stdout.strip()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-lock", action="store_true", help="Maintainer-only: pin initially downloaded artifact hashes")
    prepare(parser.parse_args().record_lock)
