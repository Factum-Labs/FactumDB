from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PipelineStage(StrEnum):
    VERIFY_EVIDENCE = "verify_evidence"
    VALIDATE_PAGES = "validate_pages"
    EXTRACT_SCHEMA = "extract_schema"
    EXTRACT_PHYSICAL_ROWS = "extract_physical_rows"
    DECODE_BINARY_LOGS = "decode_binary_logs"
    NORMALIZE_EVIDENCE = "normalize_evidence"
    GROUP_TRANSACTIONS = "group_transactions"
    CORRELATE_RECORDS = "correlate_records"
    RECONSTRUCT_STATE = "reconstruct_state"
    RECONCILE_RECORDS = "reconcile_records"


ANALYSIS_STAGES: tuple[PipelineStage, ...] = tuple(PipelineStage)


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class StageAttempt:
    number: int
    status: StageStatus
    started_at: datetime
    finished_at: datetime | None = None
    item_count: int = 0
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("attempt number must be positive")
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        if self.finished_at is not None and self.finished_at.tzinfo is None:
            raise ValueError("finished_at must be timezone-aware")
        if self.item_count < 0:
            raise ValueError("item_count must not be negative")


@dataclass(frozen=True, slots=True)
class StageState:
    stage: PipelineStage
    status: StageStatus = StageStatus.PENDING
    attempts: tuple[StageAttempt, ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineRun:
    id: str
    case_id: str
    created_at: datetime
    stages: tuple[StageState, ...]
    cancel_requested: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.case_id.strip():
            raise ValueError("pipeline and case ids must not be empty")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        stage_ids = tuple(state.stage for state in self.stages)
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("pipeline stages must be unique")

    @property
    def complete(self) -> bool:
        return bool(self.stages) and all(
            state.status in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
            for state in self.stages
        )

    @property
    def stopped(self) -> bool:
        return self.complete or any(
            state.status in {StageStatus.FAILED, StageStatus.CANCELLED}
            for state in self.stages
        )

    def state_for(self, stage: PipelineStage) -> StageState:
        for state in self.stages:
            if state.stage is stage:
                return state
        raise KeyError(stage)


@dataclass(frozen=True, slots=True)
class PipelineProgress:
    run_id: str
    case_id: str
    stage: PipelineStage
    status: StageStatus
    completed_stages: int
    total_stages: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class StageOutcome:
    item_count: int = 0
    message: str = ""

    def __post_init__(self) -> None:
        if self.item_count < 0:
            raise ValueError("item_count must not be negative")


@dataclass(frozen=True, slots=True)
class PipelineExecutionContext:
    run_id: str
    case_id: str
