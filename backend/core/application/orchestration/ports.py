from __future__ import annotations

from typing import Protocol

from core.application.orchestration.models import (
    PipelineExecutionContext,
    PipelineProgress,
    PipelineRun,
    PipelineStage,
    StageOutcome,
)


class PipelineRepository(Protocol):
    def save(self, run: PipelineRun) -> None: ...

    def get(self, run_id: str) -> PipelineRun | None: ...

    def active_for_case(self, case_id: str) -> PipelineRun | None: ...


class ProgressPublisher(Protocol):
    def publish(self, progress: PipelineProgress) -> None: ...


class PipelineStageHandler(Protocol):
    @property
    def stage(self) -> PipelineStage: ...

    @property
    def retryable(self) -> bool: ...

    def execute(self, context: PipelineExecutionContext) -> StageOutcome: ...
