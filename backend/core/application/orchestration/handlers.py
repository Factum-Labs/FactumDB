from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from core.application.models import (
    EvidenceKind,
    EvidenceStageRequest,
    OperationReceipt,
    VerifyEvidenceRequest,
)
from core.application.orchestration.models import (
    PipelineExecutionContext,
    PipelineStage,
    StageOutcome,
)
from core.application.ports import EvidenceRepository


class EvidenceOperation(Protocol):
    def execute(self, request: EvidenceStageRequest) -> OperationReceipt: ...


class VerifyOperation(Protocol):
    def execute(self, request: VerifyEvidenceRequest) -> object: ...


class VerifyEvidenceStageHandler:
    stage = PipelineStage.VERIFY_EVIDENCE
    retryable = False

    def __init__(self, evidence: EvidenceRepository, operation: VerifyOperation) -> None:
        self._evidence = evidence
        self._operation = operation

    def execute(self, context: PipelineExecutionContext) -> StageOutcome:
        items = tuple(self._evidence.list_for_case(context.case_id))
        for evidence in items:
            self._operation.execute(VerifyEvidenceRequest(context.case_id, evidence.id))
        return StageOutcome(len(items), f"verified {len(items)} evidence files")


class EvidenceStageHandler:
    retryable = True

    def __init__(
        self,
        stage: PipelineStage,
        kinds: frozenset[EvidenceKind],
        evidence: EvidenceRepository,
        operation: EvidenceOperation,
    ) -> None:
        self._stage = stage
        self._kinds = kinds
        self._evidence = evidence
        self._operation = operation

    @property
    def stage(self) -> PipelineStage:
        return self._stage

    def execute(self, context: PipelineExecutionContext) -> StageOutcome:
        items = tuple(
            item
            for item in self._evidence.list_for_case(context.case_id)
            if item.kind in self._kinds
        )
        count = 0
        for evidence in items:
            receipt = self._operation.execute(
                EvidenceStageRequest(context.case_id, evidence.id)
            )
            count += receipt.item_count
        return StageOutcome(count, f"processed {len(items)} evidence files")


class CaseStageHandler:
    retryable = True

    def __init__(
        self,
        stage: PipelineStage,
        operation: Callable[[str], object],
        item_counter: Callable[[object], int] = lambda result: 1,
    ) -> None:
        self._stage = stage
        self._operation = operation
        self._item_counter = item_counter

    @property
    def stage(self) -> PipelineStage:
        return self._stage

    def execute(self, context: PipelineExecutionContext) -> StageOutcome:
        result = self._operation(context.case_id)
        count = self._item_counter(result)
        return StageOutcome(count, f"{self.stage.value} completed")
