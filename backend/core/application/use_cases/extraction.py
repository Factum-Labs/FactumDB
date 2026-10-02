from __future__ import annotations

from collections.abc import Sequence

from core.application.errors import ConflictError
from core.application.models import EvidenceKind, EvidenceStageRequest, OperationReceipt
from core.application.ports import (
    BinlogDecoder,
    BinlogIndexReader,
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
from core.domain.models.canonical import BinlogInventory, PhysicalRecord, Schema


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
        result = self._validator.validate(request.case_id, request.evidence_id, evidence.verified_working_path)
        self._results.save_integrity(request.case_id, request.evidence_id, result.primary_tool_run_id, result.value)
        return OperationReceipt(request.case_id, "page_validation", self._clock.now(), 1, result.contributing_tool_run_ids)


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
        result = self._extractor.extract(request.case_id, request.evidence_id, evidence.verified_working_path)
        schemas: Sequence[Schema] = tuple(result.value)
        self._results.save_schemas(request.case_id, request.evidence_id, result.primary_tool_run_id, schemas)
        return OperationReceipt(
            request.case_id, "schema_extraction", self._clock.now(), len(schemas), result.contributing_tool_run_ids
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
        result = self._extractor.extract(request.case_id, request.evidence_id, evidence.verified_working_path)
        records: Sequence[PhysicalRecord] = tuple(result.value)
        if result.batches:
            for batch in result.batches:
                self._results.save_physical_records(
                    request.case_id, request.evidence_id, batch.tool_run_id, batch.value,
                )
        else:
            self._results.save_physical_records(
                request.case_id, request.evidence_id, result.primary_tool_run_id, records,
            )
        return OperationReceipt(
            request.case_id, "physical_row_extraction", self._clock.now(), len(records), result.contributing_tool_run_ids
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
        result = self._decoder.decode(request.case_id, request.evidence_id, evidence.verified_working_path)
        decoded = result.value
        self._results.save_decoded_binlog(request.case_id, request.evidence_id, result.primary_tool_run_id, decoded)
        count = len(decoded.events) + len(decoded.markers)
        return OperationReceipt(request.case_id, "binlog_decoding", self._clock.now(), count, result.contributing_tool_run_ids)


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


class RecordBinlogInventoryUseCase:
    """Compare the server's binlog index with the binlogs that were seized.

    With no index registered nothing is recorded, and the analysis treats
    binlog coverage as unknown rather than complete. More than one index is
    refused: a case is one server, and two indexes could give two different
    answers to "is any log missing".
    """

    def __init__(
        self,
        evidence: EvidenceRepository,
        reader: BinlogIndexReader,
        results: ExtractionRepository,
        clock: Clock,
    ) -> None:
        self._evidence = evidence
        self._reader = reader
        self._results = results
        self._clock = clock

    def execute(self, case_id: str) -> OperationReceipt:
        items = self._evidence.list_for_case(case_id)
        indexes = [item for item in items if item.kind is EvidenceKind.BINLOG_INDEX]
        if not indexes:
            return OperationReceipt(case_id, "binlog_inventory", self._clock.now(), 0)
        if len(indexes) > 1:
            raise ConflictError("more than one binlog index is registered for this case")

        index = require_verified_evidence(
            self._evidence, case_id, indexes[0].id, {EvidenceKind.BINLOG_INDEX}
        )
        assert index.verified_working_path is not None
        listed = tuple(self._reader.read(index.verified_working_path))
        present = tuple(item.filename for item in items if item.kind is EvidenceKind.BINLOG)
        seized = set(present)
        inventory = BinlogInventory(
            index_file=index.filename,
            listed_files=listed,
            present_files=present,
            missing_files=tuple(name for name in listed if name not in seized),
        )
        self._results.save_inventory(case_id, index.id, inventory)
        return OperationReceipt(case_id, "binlog_inventory", self._clock.now(), len(listed))
