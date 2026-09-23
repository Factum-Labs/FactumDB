"""Application filesystem contracts."""
from __future__ import annotations

from typing import Protocol
from core.application.models import Case, EvidenceFile, EvidenceMetadata, RawOutputReference


class CaseWorkspace(Protocol):
    def create(self, case_id: str) -> str: ...

    def discard(self, workspace_path: str) -> None: ...


class EvidenceInspector(Protocol):
    def inspect(self, source_path: str) -> EvidenceMetadata: ...


class FileHasher(Protocol):
    def sha256(self, path: str) -> str: ...


class WorkingCopyManager(Protocol):
    def create(self, case: Case, evidence: EvidenceFile) -> str: ...

    def discard(self, path: str) -> None: ...


class RawOutputStore(Protocol):
    def save(
        self, case: Case, tool_run_id: str, stream_name: str, content: bytes
    ) -> RawOutputReference: ...
