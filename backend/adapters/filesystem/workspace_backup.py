"""Consistent, checksummed workspace archives. Restore validates before activation."""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from core.engine import ENGINE_REVISION

FORMAT = "factumdb-workspace-backup"
VERSION = 1


def is_database(relative):
    parts = PurePosixPath(relative).parts
    return relative == "catalog.db" or (
        len(parts) == 3 and parts[0] == "cases" and parts[2] == "case.db"
    )


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(root):
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Workspace contains a symbolic link; backup cannot follow it")
        if path.is_file() and not path.name.endswith(("-wal", "-shm", "-journal")):
            relative = path.relative_to(root).as_posix()
            if relative in ("catalog.db", "settings.json") or relative.startswith("cases/"):
                yield path, relative


def usage(root):
    categories = {
        "working": 0,
        "raw-output": 0,
        "reports": 0,
        "logs": 0,
        "databases_and_settings": 0,
    }
    cases = {}
    for path, relative in files(root):
        size = path.stat().st_size
        parts = PurePosixPath(relative).parts
        category = (
            parts[2] if len(parts) > 2 and parts[2] in categories else "databases_and_settings"
        )
        categories[category] += size
        if len(parts) > 1 and parts[0] == "cases":
            cases[parts[1]] = cases.get(parts[1], 0) + size
    # WAL bytes also occupy disk, although snapshots omit these transient files.
    journal_bytes = sum(
        p.stat().st_size
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink() and p.name.endswith(("-wal", "-shm", "-journal"))
    )
    categories["databases_and_settings"] += journal_bytes
    return {
        "categories": categories,
        "cases": cases,
        "total_bytes": sum(categories.values()),
        "free_bytes": shutil.disk_usage(root).free,
    }


def create_backup(root, destination):
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(root):
        raise ValueError("Save the backup outside the workspace")
    if destination.exists():
        raise FileExistsError("Choose a new backup filename")
    with tempfile.TemporaryDirectory(prefix="factumdb-backup-") as temporary:
        snapshot = Path(temporary)
        entries = {}
        for source, relative in files(root):
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if is_database(relative):
                source_db = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
                target_db = sqlite3.connect(target)
                try:
                    source_db.backup(target_db)
                finally:
                    source_db.close()
                    target_db.close()
            else:
                shutil.copyfile(source, target)
            entries[relative] = {"size": target.stat().st_size, "sha256": digest(target)}
        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "engine_revision": ENGINE_REVISION,
            "workspace": str(root),
            "files": entries,
            "original_evidence_included": False,
        }
        # Write beside the destination; rename only after verification succeeds.
        fd, pending = tempfile.mkstemp(prefix=".factumdb-backup-", dir=destination.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                for relative in entries:
                    archive.write(snapshot / relative, relative)
            inspect_backup(pending)
            # Exclusive destination creation prevents overwriting another backup.
            with destination.open("xb") as output, open(pending, "rb") as source:
                shutil.copyfileobj(source, output)
        finally:
            Path(pending).unlink(missing_ok=True)
    return {"path": str(destination), "files": len(entries)}


def inspect_backup(path, *, extract_to=None):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Invalid backup contents")
        if archive.getinfo("manifest.json").file_size > 8 * 1024 * 1024:
            raise ValueError("Backup manifest is too large")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValueError("Unsupported workspace backup format")
        if (
            type(manifest.get("engine_revision")) is not int
            or manifest["engine_revision"] > ENGINE_REVISION
        ):
            raise ValueError("This backup requires a newer FactumDB engine")
        entries = manifest.get("files")
        if not isinstance(entries, dict) or set(names) != {"manifest.json", *entries}:
            raise ValueError("Backup file inventory does not match")
        if "catalog.db" not in entries:
            raise ValueError("Backup is missing its account and case catalog")
        for info in infos:
            if info.filename == "manifest.json":
                continue
            relative = PurePosixPath(info.filename)
            if (
                relative.is_absolute()
                or any(part in ("..", ".") for part in relative.parts)
                or "\\" in info.filename
                or ":" in info.filename
                or stat.S_ISLNK(info.external_attr >> 16)
                or (
                    info.filename not in ("catalog.db", "settings.json")
                    and not info.filename.startswith("cases/")
                )
            ):
                raise ValueError("Unsafe path in backup")
            entry = entries[info.filename]
            if type(entry.get("size")) is not int or info.file_size != entry["size"]:
                raise ValueError("Backup size does not match manifest")
        total = sum(entry["size"] for entry in entries.values())
        if extract_to and total > shutil.disk_usage(extract_to).free:
            raise ValueError("Not enough disk space to restore this backup")
        for relative, entry in entries.items():
            hasher = hashlib.sha256()
            target = Path(extract_to) / relative if extract_to else None
            if target:
                target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(relative) as source:
                output = target.open("xb") if target else None
                try:
                    while block := source.read(1024 * 1024):
                        hasher.update(block)
                        if output:
                            output.write(block)
                finally:
                    if output:
                        output.close()
            if hasher.hexdigest() != entry["sha256"]:
                raise ValueError(f"Backup checksum mismatch: {relative}")
            if (
                target
                and len(PurePosixPath(relative).parts) > 2
                and PurePosixPath(relative).parts[2] == "working"
            ):
                target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return {
            **manifest,
            "total_bytes": total,
            "case_count": len(
                {
                    PurePosixPath(name).parts[1]
                    for name in entries
                    if name.startswith("cases/") and len(PurePosixPath(name).parts) > 2
                }
            ),
        }


def rebase_and_validate(staging, original, destination, device_identity):
    """Update paths used to read restored files; leave provenance JSON and source paths intact."""
    old_root = str(original).rstrip("/\\")
    for path, relative in files(staging):
        if not is_database(relative):
            continue
        with closing(sqlite3.connect(path)) as connection, connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Backup contains a damaged database")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Backup contains invalid database references")
            for table, columns in (
                ("cases", ("workspace_path",)),
                ("evidence_files", ("working_copy_path",)),
                ("tool_runs", ("stdout_path", "stderr_path")),
            ):
                for column in columns:
                    for rowid, value in connection.execute(f"SELECT rowid, {column} FROM {table}"):
                        if value is None:
                            continue
                        normalized = value.replace("\\", "/")
                        prefix = old_root.replace("\\", "/") + "/"
                        if normalized.startswith(prefix):
                            suffix = normalized[len(prefix) :]
                            relative = PurePosixPath(suffix)
                            if relative.is_absolute() or ".." in relative.parts or ":" in suffix:
                                raise ValueError("Unsafe workspace path in backup database")
                            connection.execute(
                                f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                                (str(destination.joinpath(*relative.parts)), rowid),
                            )
                        elif table == "cases" or column == "working_copy_path":
                            raise ValueError(
                                "Backup database references files outside its workspace"
                            )
    with closing(sqlite3.connect(staging / "catalog.db")) as catalog:
        if not catalog.execute(
            "SELECT 1 FROM users WHERE device_identity = ?", (device_identity,)
        ).fetchone():
            raise ValueError(
                "This backup has no account for the current OS identity; "
                "cross-device account migration is required"
            )
        for case_id, workspace in catalog.execute("SELECT case_id, workspace_path FROM cases"):
            if (
                not case_id
                or any(character in case_id for character in "/\\:")
                or case_id in (".", "..")
            ):
                raise ValueError("Invalid case ID in backup")
            if Path(workspace) != destination / "cases" / case_id:
                raise ValueError("Case workspace does not match its catalog entry")
            case_db = staging / "cases" / case_id / "case.db"
            if not case_db.is_file():
                raise ValueError("Backup is missing a case database")
            with closing(sqlite3.connect(case_db)) as case:
                if not case.execute("SELECT 1 FROM cases WHERE case_id = ?", (case_id,)).fetchone():
                    raise ValueError("Case database does not match its catalog entry")
