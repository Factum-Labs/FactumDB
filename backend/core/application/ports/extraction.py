"""Application extraction contracts."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from core.application.models import DecodedBinlog, NormalizedEvidence
from core.domain.models.canonical import IntegrityResult, PhysicalRecord, Schema


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
