"""Assemble the analysis pipeline at the outer application boundary.

Construction performs no I/O. Repositories, normalization and event delivery are
explicit dependencies; this module never falls back to temporary storage.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from adapters.tools import (
    Ibd2SdiAdapter, Ibd2SdiSchemaExtractor, Ibd2SqlAdapter,
    Ibd2SqlPhysicalRowExtractor, InnochecksumAdapter, MysqlBinlogAdapter,
    MysqlBinlogDecoder,
)
from core.application.models import EvidenceKind, EvidenceStageRequest, OperationReceipt
from core.application.orchestration.handlers import (
    CaseStageHandler, EvidenceStageHandler, VerifyEvidenceStageHandler,
)
from core.application.orchestration.models import PipelineStage
from core.application.orchestration.pipeline import AnalysisOrchestrator
from core.application.orchestration.ports import PipelineRepository, ProgressPublisher
from core.application.ports import (
    BinlogDecoder, CaseRepository, Clock, DomainRepository, EvidenceNormalizer,
    EvidenceRepository, ExtractionRepository, FileHasher, IdGenerator,
    PageValidator, PhysicalRowExtractor, SchemaExtractor, WorkingCopyManager,
)
from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase, GroupTransactionsUseCase,
    ReconcileRecordsUseCase, ReconstructStateUseCase,
)
from core.application.use_cases.evidence import VerifyEvidenceUseCase
from core.application.use_cases.extraction import (
    DecodeBinaryLogsUseCase, ExtractPhysicalRowsUseCase, ExtractSchemaUseCase,
    NormalizeEvidenceUseCase, RunPageValidationUseCase,
)
from core.domain.models.correlation import CorrelationResult
from core.domain.models.history import ReconstructionResult
from core.domain.models.reconciliation import ReconciliationResult
from core.domain.models.transactions import GroupingResult
from core.domain.ports import SchemaCatalog


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineDependencies:
    cases: CaseRepository
    evidence: EvidenceRepository
    copies: WorkingCopyManager
    hasher: FileHasher
    extraction: ExtractionRepository
    normalizer: EvidenceNormalizer
    domain: DomainRepository
    pipelines: PipelineRepository
    progress: ProgressPublisher
    ids: IdGenerator
    clock: Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractionAdapters:
    page_validator: PageValidator
    schema_extractor: SchemaExtractor
    row_extractor: PhysicalRowExtractor
    # Resolve the decoder at execution time, after schema extraction has finished.
    decoder_for_case: Callable[[str], BinlogDecoder]


def build_tool_adapters(
    schemas_for_case: Callable[[str], SchemaCatalog],
    *,
    ibd2sdi_path: str = "ibd2sdi",
    innochecksum_path: str = "innochecksum",
    ibd2sql_path: str | None = None,
    python_path: str = "python3",
    mysqlbinlog_path: str = "mysqlbinlog",
    include_deleted: bool = False,
) -> ExtractionAdapters:
    """Configure real tools without launching them or reading schemas yet.

    schemas_for_case must return a catalog restricted to the requested case.
    It is deliberately independent of DomainRepository.inputs_for: a complete
    domain input bundle may not exist until normalization has finished.
    """
    def decoder_for_case(case_id: str) -> BinlogDecoder:
        return MysqlBinlogDecoder(
            MysqlBinlogAdapter(mysqlbinlog_path), schemas_for_case(case_id).schema_for,
        )

    return ExtractionAdapters(
        page_validator=InnochecksumAdapter(innochecksum_path),
        schema_extractor=Ibd2SdiSchemaExtractor(Ibd2SdiAdapter(ibd2sdi_path)),
        row_extractor=Ibd2SqlPhysicalRowExtractor(
            Ibd2SqlAdapter(ibd2sql_path, python_path), include_deleted=include_deleted,
        ),
        decoder_for_case=decoder_for_case,
    )


def build_analysis_pipeline(
    dependencies: PipelineDependencies, adapters: ExtractionAdapters,
) -> AnalysisOrchestrator:
    """Wire all ten analysis stages, from verification through reconciliation.

    Case creation and registration happen before start(). The extraction store,
    normalizer and domain repository must share the same case data. This factory
    retains the orchestrator's existing retry/cancellation policy.
    """
    d = dependencies
    ibd = frozenset({EvidenceKind.IBD})
    verify = VerifyEvidenceUseCase(d.cases, d.evidence, d.copies, d.hasher)
    validate = RunPageValidationUseCase(d.evidence, adapters.page_validator, d.extraction, d.clock)
    schema = ExtractSchemaUseCase(d.evidence, adapters.schema_extractor, d.extraction, d.clock)
    rows = ExtractPhysicalRowsUseCase(d.evidence, adapters.row_extractor, d.extraction, d.clock)
    normalize = NormalizeEvidenceUseCase(d.cases, d.normalizer, d.extraction, d.clock)
    group = GroupTransactionsUseCase(d.domain)
    correlate = CorrelateRecordsUseCase(d.domain)
    reconstruct = ReconstructStateUseCase(d.domain)
    reconcile = ReconcileRecordsUseCase(d.domain)

    def binlog_skip_reason(case_id: str) -> str | None:
        if not any(item.kind is EvidenceKind.BINLOG for item in d.evidence.list_for_case(case_id)):
            return "No binlog evidence registered in this case"
        return None

    def decode_case(case_id: str) -> OperationReceipt:
        decoder = adapters.decoder_for_case(case_id)
        operation = DecodeBinaryLogsUseCase(d.evidence, decoder, d.extraction, d.clock)
        count = 0
        for item in d.evidence.list_for_case(case_id):
            if item.kind is EvidenceKind.BINLOG:
                count += operation.execute(EvidenceStageRequest(case_id, item.id)).item_count
        return OperationReceipt(case_id, "binlog_decoding", d.clock.now(), count)

    handlers = (
        VerifyEvidenceStageHandler(d.evidence, verify),
        EvidenceStageHandler(PipelineStage.VALIDATE_PAGES, ibd, d.evidence, validate),
        EvidenceStageHandler(PipelineStage.EXTRACT_SCHEMA, ibd, d.evidence, schema),
        EvidenceStageHandler(PipelineStage.EXTRACT_PHYSICAL_ROWS, ibd, d.evidence, rows),
        CaseStageHandler(PipelineStage.DECODE_BINARY_LOGS, decode_case,
                         lambda value: cast(OperationReceipt, value).item_count,
                         skip_reason=binlog_skip_reason),
        CaseStageHandler(PipelineStage.NORMALIZE_EVIDENCE, normalize.execute,
                         lambda value: cast(OperationReceipt, value).item_count),
        CaseStageHandler(PipelineStage.GROUP_TRANSACTIONS, group.execute,
                         lambda value: len(cast(GroupingResult, value).transactions)),
        CaseStageHandler(PipelineStage.CORRELATE_RECORDS, correlate.execute,
                         lambda value: len(cast(CorrelationResult, value).records)),
        CaseStageHandler(PipelineStage.RECONSTRUCT_STATE, reconstruct.execute,
                         lambda value: len(cast(ReconstructionResult, value).histories)),
        CaseStageHandler(PipelineStage.RECONCILE_RECORDS, reconcile.execute,
                         lambda value: len(cast(ReconciliationResult, value).rows)),
    )
    return AnalysisOrchestrator(d.cases, d.pipelines, d.progress, handlers, d.ids, d.clock)
