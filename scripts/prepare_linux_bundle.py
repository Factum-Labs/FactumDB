"""Stage checksum-locked MySQL utilities and ibd2sql for Linux x86-64."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".bundle-cache"
RESOURCES = ROOT / "src-tauri/resources"
RUNTIME = RESOURCES / "runtime/linux"
LOCK = ROOT / "scripts/linux-bundle.lock.json"
TOOLS = ("innochecksum", "ibd2sdi", "mysqlbinlog")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(record=False):
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise SystemExit("Build this bundle on Linux x86-64 (Ubuntu WSL is supported).")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    CACHE.mkdir(exist_ok=True)
    archives = {}
    for key, item in lock["artifacts"].items():
        path = CACHE / item["filename"]
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".download")
            subprocess.run(["curl", "-fL", "--retry", "3", item["url"], "-o", str(temporary)], check=True)
            temporary.replace(path)
        checksum = digest(path)
        if record:
            item["sha256"] = checksum
        elif checksum != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path.name}")
        archives[key] = path
    if record:
        LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    if RUNTIME.exists():
        RUNTIME.resolve().relative_to(RESOURCES.resolve())
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True)
    # Copy only utilities, their private libraries and license/build information.
    # Never stage mysqld or install a database service.
    with tarfile.open(archives["mysql"]) as archive:
        for entry in archive:
            parts = Path(entry.name).parts[1:]
            if not parts:
                continue
            relative = Path(*parts)
            selected = (relative.as_posix() in {f"bin/{name}" for name in TOOLS}
                        or parts[0] == "lib"
                        or relative.as_posix() in {"LICENSE", "README", "docs/INFO_BIN", "docs/INFO_SRC"})
            if not selected or entry.isdir():
                continue
            target = (RUNTIME / "mysql" / relative).resolve()
            target.relative_to((RUNTIME / "mysql").resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.isfile():
                with archive.extractfile(entry) as incoming, target.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(entry.mode & 0o777)
            elif entry.issym():
                # Resolve vendor symlinks within the staged tree only.
                (target.parent / entry.linkname).resolve().relative_to((RUNTIME / "mysql").resolve())
                target.symlink_to(entry.linkname)
            else:
                raise ValueError(f"Unsupported archive member: {entry.name}")
    with zipfile.ZipFile(archives["ibd2sql"]) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            target = (RUNTIME / "ibd2sql").joinpath(*Path(entry.filename).parts[1:]).resolve()
            target.relative_to((RUNTIME / "ibd2sql").resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as incoming, target.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
    tools = {"ibd2sql_path": "ibd2sql/main.py"}
    for name in TOOLS:
        binary = RUNTIME / "mysql/bin" / name
        needed = subprocess.check_output(["patchelf", "--print-needed", str(binary)], text=True)
        # Ubuntu 24.04 renamed libaio's SONAME during its time_t transition.
        # The x86-64 ABI is compatible; use the distribution's maintained library.
        if "libaio.so.1\n" in needed:
            subprocess.run(["patchelf", "--replace-needed", "libaio.so.1", "libaio.so.1t64", str(binary)], check=True)
        subprocess.run(["patchelf", "--force-rpath", "--set-rpath",
                        "$ORIGIN/../lib/private:$ORIGIN/../lib", str(binary)], check=True)
        tools[f"{name}_path"] = f"mysql/bin/{name}"
    sources = RESOURCES / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    for key in ("mysql_source", "ibd2sql"):
        shutil.copy2(archives[key], sources / archives[key].name)
    (RUNTIME / "THIRD-PARTY-NOTICES.txt").write_text(
        "FactumDB Linux x86-64 utilities\n\n"
        f"MySQL Community {lock['artifacts']['mysql']['version']}: https://www.mysql.com/ (mysql/LICENSE).\n"
        "Complete corresponding source and build instructions: ../../sources/mysql-8.4.11.tar.gz.\n"
        "ibd2sql: https://github.com/ddcw/ibd2sql (ibd2sql/LICENSE).\n"
        "Complete source: ibd2sql/ and ../../sources/ibd2sql-e6e8c380.zip.\n"
        "Python and desktop libraries are provided by the Linux distribution.\n"
        "Artifact versions and SHA-256 hashes: manifest.json.\n", encoding="utf-8")
    for key, relative in tools.items():
        command = [str(RUNTIME / relative), "--version"]
        if key == "ibd2sql_path":
            command = [sys.executable, "-B", *command]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"{key}: {result.stderr}")
        print(result.stdout.strip(), flush=True)
    manifest = {"target": lock["target"], "tools": tools, "artifacts": lock["artifacts"],
                "files": {p.relative_to(RUNTIME).as_posix(): digest(p)
                          for p in sorted(RUNTIME.rglob("*")) if p.is_file()}}
    (RUNTIME / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged Linux runtime: {RUNTIME}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-lock", action="store_true", help="Maintainer only: review and pin downloaded artifact hashes")
    prepare(parser.parse_args().record_lock)
