"""Application extraction contracts."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from core.application.models import DecodedBinlog, NormalizedEvidence, ProvenancedResult
from core.domain.models.canonical import (
    BinlogInventory, IntegrityResult, PhysicalRecord, Schema,
)


class PageValidator(Protocol):
    def validate(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[IntegrityResult]: ...


class SchemaExtractor(Protocol):
    def extract(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[Sequence[Schema]]: ...


class PhysicalRowExtractor(Protocol):
    def extract(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[Sequence[PhysicalRecord]]: ...


class BinlogDecoder(Protocol):
    def decode(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[DecodedBinlog]: ...


class BinlogIndexReader(Protocol):
    def read(self, working_copy_path: str) -> Sequence[str]:
        """The binlog file names a mysql-bin.index lists, oldest first."""
        ...


class EvidenceNormalizer(Protocol):
    def normalize(self, case_id: str) -> NormalizedEvidence: ...


class ExtractionRepository(Protocol):
    def save_integrity(
        self, case_id: str, evidence_id: str, tool_run_id: str, result: IntegrityResult
    ) -> None: ...

    def save_schemas(self, case_id: str, evidence_id: str, tool_run_id: str, schemas: Sequence[Schema]) -> None: ...

    def save_physical_records(
        self, case_id: str, evidence_id: str, tool_run_id: str, records: Sequence[PhysicalRecord]
    ) -> None: ...

    def save_decoded_binlog(
        self, case_id: str, evidence_id: str, tool_run_id: str, decoded: DecodedBinlog
    ) -> None:
        """Persist events, markers AND warnings with the case/evidence association.

        Warnings describe skipped or unsupported input and must not be discarded
        when a decode produces no events. Concrete persistence is responsible for
        saving the complete bundle atomically.
        """
        ...

    def save_normalized(self, case_id: str, normalized: NormalizedEvidence) -> None: ...

    def save_inventory(
        self, case_id: str, evidence_id: str, inventory: BinlogInventory
    ) -> None:
        """Store what a binlog index listed against what was seized.

        evidence_id is the index file's own evidence id.
        """
        ...
