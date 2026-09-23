from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.application.models import EvidenceKind, EvidenceMetadata


_BINLOG = re.compile(r"^(?:mysql-bin|binlog)\.\d+$", re.IGNORECASE)


def _kind(filename: str) -> EvidenceKind:
    lowered = filename.lower()
    if lowered.endswith(".ibd"):
        return EvidenceKind.IBD
    if lowered == "mysql-bin.index" or lowered == "binlog.index":
        return EvidenceKind.BINLOG_INDEX
    if _BINLOG.fullmatch(filename) is not None:
        return EvidenceKind.BINLOG
    raise ValueError(f"unsupported evidence file: {filename}")


class FilesystemEvidenceInspector:
    def inspect(self, source_path: str) -> EvidenceMetadata:
        path = Path(source_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"evidence path is not a regular file: {path}")
        stat = path.stat()
        return EvidenceMetadata(str(path), path.name, stat.st_size, _kind(path.name))


class Sha256FileHasher:
    """Calculates SHA-256 without loading the evidence file into memory."""

    def __init__(self, chunk_size: int = 1024 * 1024) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._chunk_size = chunk_size

    def sha256(self, path: str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            while chunk := stream.read(self._chunk_size):
                digest.update(chunk)
        return digest.hexdigest()
