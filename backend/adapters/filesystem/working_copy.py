from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

from adapters.filesystem._paths import contained, safe_component
from core.application.errors import EvidenceIntegrityError
from core.application.models import Case, EvidenceFile


class FilesystemWorkingCopyManager:
    """Creates an atomic, read-only copy while leaving source evidence untouched."""

    def __init__(self, workspace_root: str | Path, chunk_size: int = 1024 * 1024) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._root = Path(workspace_root).expanduser().resolve(strict=False)
        self._chunk_size = chunk_size

    def create(self, case: Case, evidence: EvidenceFile) -> str:
        workspace = contained(self._root, Path(case.workspace_path))
        if workspace == self._root or not workspace.is_dir():
            raise ValueError(f"case workspace does not exist: {workspace}")
        if evidence.case_id != case.id:
            raise ValueError("evidence does not belong to the supplied case")
        safe_component(evidence.id, "evidence id")
        safe_component(evidence.filename, "evidence filename")

        source = Path(evidence.source_path).resolve(strict=True)
        if not source.is_file():
            raise ValueError(f"evidence path is not a regular file: {source}")
        working = contained(workspace, workspace / "working")
        working.mkdir(exist_ok=True)
        destination = contained(working, working / f"{evidence.id}-{evidence.filename}")
        if destination.exists():
            raise FileExistsError(f"working copy already exists: {destination}")

        before = source.stat()
        temporary_name: str | None = None
        published = False
        try:
            with source.open("rb") as original, tempfile.NamedTemporaryFile(
                mode="wb", dir=working, prefix=".copy-", delete=False
            ) as temporary:
                temporary_name = temporary.name
                shutil.copyfileobj(original, temporary, length=self._chunk_size)
                temporary.flush()
                os.fsync(temporary.fileno())
            after = source.stat()
            observed_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            observed_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if observed_before != observed_after:
                raise EvidenceIntegrityError("source evidence changed while it was being copied")

            # A hard link publishes the completed temporary file without replacing
            # an existing destination. Both files are in the same directory/filesystem.
            os.link(temporary_name, destination)
            published = True
            Path(temporary_name).unlink()
            temporary_name = None
            destination.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            return str(destination)
        except Exception:
            if published and destination.exists():
                destination.chmod(stat.S_IWUSR | stat.S_IRUSR)
                destination.unlink()
            raise
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    def discard(self, path: str) -> None:
        target = contained(self._root, Path(path))
        if target == self._root or target.is_dir():
            raise ValueError("working-copy discard target must be a file")
        if target.exists():
            target.chmod(stat.S_IWUSR | stat.S_IRUSR)
            target.unlink()
