"""Application workflow repositories contracts."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from core.domain.models.case import Case
from core.domain.models.evidence import EvidenceFile, ToolRun


class CaseRepository(Protocol):
    def save(self, case: Case) -> None: ...

    def get(self, case_id: str) -> Case | None: ...


class EvidenceRepository(Protocol):
    def save(self, evidence: EvidenceFile) -> None: ...

    def get(self, case_id: str, evidence_id: str) -> EvidenceFile | None: ...

    def find_by_source(self, case_id: str, canonical_path: str) -> EvidenceFile | None: ...

    def list_for_case(self, case_id: str) -> Sequence[EvidenceFile]: ...


class ToolRunRepository(Protocol):
    def save(self, run: ToolRun) -> None: ...

    def get(self, run_id: str) -> ToolRun | None: ...
