"""Technology-independent contracts required by application use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.application.models import (
    Case,
    DecodedBinlog,
    EvidenceFile,
    EvidenceMetadata,
    NormalizedEvidence,
    RawOutputReference,
    ToolRun,
)
from core.domain.models.canonical import IntegrityResult, PhysicalRecord, Schema
from core.domain.models.correlation import CorrelationResult
from core.domain.models.history import ReconstructionResult
from core.domain.models.reconciliation import ReconciliationResult
from core.domain.models.transactions import GroupingResult
from core.domain.ports import EvidenceContext, EventSource, PhysicalRecordSource, SchemaCatalog


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class CaseRepository(Protocol):
    def save(self, case: Case) -> None: ...

    def get(self, case_id: str) -> Case | None: ...


class CaseWorkspace(Protocol):
    def create(self, case_id: str) -> str: ...

    def discard(self, workspace_path: str) -> None: ...


class EvidenceRepository(Protocol):
    def save(self, evidence: EvidenceFile) -> None: ...

    def get(self, case_id: str, evidence_id: str) -> EvidenceFile | None: ...

    def find_by_source(self, case_id: str, canonical_path: str) -> EvidenceFile | None: ...

    def list_for_case(self, case_id: str) -> Sequence[EvidenceFile]: ...


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


class ToolRunRepository(Protocol):
    def save(self, run: ToolRun) -> None: ...

    def get(self, run_id: str) -> ToolRun | None: ...


class PageValidator(Protocol):
    def validate(self, working_copy_path: str) -> IntegrityResult: ...


class SchemaExtractor(Protocol):
    def extract(self, working_copy_path: str) -> Sequence[Schema]: ...


class PhysicalRowExtractor(Protocol):
    def extract(self, working_copy_path: str) -> Sequence[PhysicalRecord]: ...


class BinlogDecoder(Protocol):
    def decode(self, working_copy_path: str) -> DecodedBinlog: ...


class EvidenceNormalizer(Protocol):
    def normalize(self, case_id: str) -> NormalizedEvidence: ...


class ExtractionRepository(Protocol):
    def save_integrity(
        self, case_id: str, evidence_id: str, result: IntegrityResult
    ) -> None: ...

    def save_schemas(self, case_id: str, evidence_id: str, schemas: Sequence[Schema]) -> None: ...

    def save_physical_records(
        self, case_id: str, evidence_id: str, records: Sequence[PhysicalRecord]
    ) -> None: ...

    def save_decoded_binlog(
        self, case_id: str, evidence_id: str, decoded: DecodedBinlog
    ) -> None: ...

    def save_normalized(self, case_id: str, normalized: NormalizedEvidence) -> None: ...


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
