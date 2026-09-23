from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from adapters.filesystem._paths import contained, safe_component
from core.application.models import Case, RawOutputReference


class FilesystemRawOutputStore:
    """Preserves exact tool bytes and returns a digest suitable for an audit record."""

    def __init__(self, workspace_root: str | Path) -> None:
        self._root = Path(workspace_root).expanduser().resolve(strict=False)

    def save(
        self, case: Case, tool_run_id: str, stream_name: str, content: bytes
    ) -> RawOutputReference:
        safe_component(tool_run_id, "tool run id")
        safe_component(stream_name, "stream name")
        workspace = contained(self._root, Path(case.workspace_path))
        if workspace == self._root or not workspace.is_dir():
            raise ValueError(f"case workspace does not exist: {workspace}")
        directory = contained(workspace, workspace / "raw-output" / tool_run_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = contained(directory, directory / f"{stream_name}.bin")
        if destination.exists():
            raise FileExistsError(f"raw output already exists: {destination}")

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=directory, prefix=".raw-", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.link(temporary_name, destination)
            Path(temporary_name).unlink()
            temporary_name = None
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

        return RawOutputReference(
            path=str(destination),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
