from __future__ import annotations

import shutil
from pathlib import Path

from adapters.filesystem._paths import contained, safe_component


class FilesystemCaseWorkspace:
    """Creates and removes only case directories beneath one configured root."""

    _DIRECTORIES = ("working", "raw-output", "reports", "logs")

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve(strict=False)

    def create(self, case_id: str) -> str:
        safe_component(case_id, "case id")
        self._root.mkdir(parents=True, exist_ok=True)
        workspace = contained(self._root, self._root / case_id)
        workspace.mkdir(exist_ok=False)
        try:
            for name in self._DIRECTORIES:
                (workspace / name).mkdir()
        except Exception:
            shutil.rmtree(workspace)
            raise
        return str(workspace)

    def discard(self, workspace_path: str) -> None:
        workspace = contained(self._root, Path(workspace_path))
        if workspace == self._root:
            raise ValueError("refusing to discard the workspace root")
        if workspace.exists():
            shutil.rmtree(workspace)
