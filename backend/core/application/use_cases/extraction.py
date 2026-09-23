from __future__ import annotations

from collections.abc import Sequence

from core.application.models import EvidenceKind, EvidenceStageRequest, OperationReceipt
from core.application.ports import (
    BinlogDecoder,
    CaseRepository,
    Clock,
    EvidenceNormalizer,
    EvidenceRepository,
    ExtractionRepository,
    PageValidator,
    PhysicalRowExtractor,
    SchemaExtractor,
)
from core.application.use_cases._support import require_case, require_verified_evidence
from core.domain.models.canonical import PhysicalRecord, Schema


class RunPageValidationUseCase:
    def __init__(
        self,
        evidence: EvidenceRepository,
        validator: PageValidator,
        results: ExtractionRepository,
        clock: Clock,
    ) -> None:
        self._evidence = evidence
        self._validator = validator
        self._results = results
        self._clock = clock

    def execute(self, request: EvidenceStageRequest) -> OperationReceipt:
        evidence = require_verified_evidence(
            self._evidence, request.case_id, request.evidence_id, {EvidenceKind.IBD}
        )
        assert evidence.verified_working_path is not None
        result = self._validator.validate(evidence.verified_working_path)
        self._results.save_integrity(request.case_id, request.evidence_id, result)
        return OperationReceipt(request.case_id, "page_validation", self._clock.now(), 1)


class ExtractSchemaUseCase:
    def __init__(
        self,
        evidence: EvidenceRepository,
        extractor: SchemaExtractor,
        results: ExtractionRepository,
        clock: Clock,
    ) -> None:
        self._evidence = evidence
        self._extractor = extractor
        self._results = results
        self._clock = clock

    def execute(self, request: EvidenceStageRequest) -> OperationReceipt:
        evidence = require_verified_evidence(
            self._evidence, request.case_id, request.evidence_id, {EvidenceKind.IBD}
        )
        assert evidence.verified_working_path is not None
        schemas: Sequence[Schema] = tuple(self._extractor.extract(evidence.verified_working_path))
        self._results.save_schemas(request.case_id, request.evidence_id, schemas)
        return OperationReceipt(
            request.case_id, "schema_extraction", self._clock.now(), len(schemas)
        )


class ExtractPhysicalRowsUseCase:
    def __init__(
        self,
        evidence: EvidenceRepository,
        extractor: PhysicalRowExtractor,
        results: ExtractionRepository,
        clock: Clock,
    ) -> None:
        self._evidence = evidence
        self._extractor = extractor
        self._results = results
        self._clock = clock

    def execute(self, request: EvidenceStageRequest) -> OperationReceipt:
        evidence = require_verified_evidence(
            self._evidence, request.case_id, request.evidence_id, {EvidenceKind.IBD}
        )
        assert evidence.verified_working_path is not None
        records: Sequence[PhysicalRecord] = tuple(
            self._extractor.extract(evidence.verified_working_path)
        )
        self._results.save_physical_records(request.case_id, request.evidence_id, records)
        return OperationReceipt(
            request.case_id, "physical_row_extraction", self._clock.now(), len(records)
        )


class DecodeBinaryLogsUseCase:
    def __init__(
        self,
        evidence: EvidenceRepository,
        decoder: BinlogDecoder,
        results: ExtractionRepository,
        clock: Clock,
    ) -> None:
        self._evidence = evidence
        self._decoder = decoder
        self._results = results
        self._clock = clock

    def execute(self, request: EvidenceStageRequest) -> OperationReceipt:
        evidence = require_verified_evidence(
            self._evidence, request.case_id, request.evidence_id, {EvidenceKind.BINLOG}
        )
        assert evidence.verified_working_path is not None
        decoded = self._decoder.decode(evidence.verified_working_path)
        self._results.save_decoded_binlog(request.case_id, request.evidence_id, decoded)
        count = len(decoded.events) + len(decoded.markers)
        return OperationReceipt(request.case_id, "binlog_decoding", self._clock.now(), count)


class NormalizeEvidenceUseCase:
    def __init__(
        self,
        cases: CaseRepository,
        normalizer: EvidenceNormalizer,
        results: ExtractionRepository,
        clock: Clock,
    ) -> None:
        self._cases = cases
        self._normalizer = normalizer
        self._results = results
        self._clock = clock

    def execute(self, case_id: str) -> OperationReceipt:
        require_case(self._cases, case_id)
        normalized = self._normalizer.normalize(case_id)
        self._results.save_normalized(case_id, normalized)
        count = (
            len(normalized.schemas)
            + len(normalized.physical_records)
            + len(normalized.events)
            + len(normalized.markers)
        )
        return OperationReceipt(case_id, "normalization", self._clock.now(), count)
