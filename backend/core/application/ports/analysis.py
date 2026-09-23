"""Application analysis contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from core.domain.models.correlation import CorrelationResult
from core.domain.models.history import ReconstructionResult
from core.domain.models.reconciliation import ReconciliationResult
from core.domain.models.transactions import GroupingResult
from core.domain.ports import EvidenceContext, EventSource, PhysicalRecordSource, SchemaCatalog


@dataclass(frozen=True, slots=True)
class DomainInputs:
    """Case-scoped domain ports assembled by a persistence adapter."""

    schemas: SchemaCatalog
    events: EventSource
    physical: PhysicalRecordSource
    evidence: EvidenceContext


class DomainRepository(Protocol):
    def inputs_for(self, case_id: str) -> DomainInputs: ...

    def save_grouping(self, case_id: str, result: GroupingResult) -> None: ...

    def load_grouping(self, case_id: str) -> GroupingResult | None: ...

    def save_correlation(self, case_id: str, result: CorrelationResult) -> None: ...

    def load_correlation(self, case_id: str) -> CorrelationResult | None: ...

    def save_reconstruction(self, case_id: str, result: ReconstructionResult) -> None: ...

    def load_reconstruction(self, case_id: str) -> ReconstructionResult | None: ...

    def save_reconciliation(self, case_id: str, result: ReconciliationResult) -> None: ...
