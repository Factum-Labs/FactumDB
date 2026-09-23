from __future__ import annotations

from dataclasses import replace

from core.application.errors import ConflictError, NotFoundError, PrerequisiteError
from core.application.orchestration.models import (
    ANALYSIS_STAGES,
    PipelineExecutionContext,
    PipelineProgress,
    PipelineRun,
    PipelineStage,
    StageAttempt,
    StageState,
    StageStatus,
)
from core.application.orchestration.ports import (
    PipelineRepository,
    PipelineStageHandler,
    ProgressPublisher,
)
from core.application.ports import CaseRepository, Clock, IdGenerator


class AnalysisOrchestrator:
    """Runs configured handlers in order while persisting every transition."""

    def __init__(
        self,
        cases: CaseRepository,
        repository: PipelineRepository,
        publisher: ProgressPublisher,
        handlers: tuple[PipelineStageHandler, ...],
        ids: IdGenerator,
        clock: Clock,
        stages: tuple[PipelineStage, ...] = ANALYSIS_STAGES,
    ) -> None:
        self._cases = cases
        self._repository = repository
        self._publisher = publisher
        self._handlers = {handler.stage: handler for handler in handlers}
        self._ids = ids
        self._clock = clock
        self._stages = stages
        if len(stages) != len(set(stages)):
            raise ValueError("orchestrator stages must be unique")
        if len(handlers) != len(self._handlers):
            raise ValueError("pipeline handlers must have unique stages")
        missing = set(stages) - set(self._handlers)
        if missing:
            names = ", ".join(sorted(stage.value for stage in missing))
            raise ValueError(f"missing pipeline handlers: {names}")

    def start(self, case_id: str) -> PipelineRun:
        if self._cases.get(case_id) is None:
            raise NotFoundError(f"case not found: {case_id}")
        active = self._repository.active_for_case(case_id)
        if active is not None and not active.stopped:
            raise ConflictError(f"case already has an active pipeline: {active.id}")
        run = PipelineRun(
            id=self._ids.new_id(),
            case_id=case_id,
            created_at=self._clock.now(),
            stages=tuple(StageState(stage) for stage in self._stages),
        )
        self._repository.save(run)
        return run

    def run_next(self, run_id: str) -> PipelineRun:
        run = self._require_run(run_id)
        if run.complete or run.stopped:
            return run
        if run.cancel_requested:
            return self._cancel_pending(run)

        index = next(
            (i for i, state in enumerate(run.stages) if state.status is StageStatus.PENDING),
            None,
        )
        if index is None:
            return run
        previous = run.stages[:index]
        if any(
            state.status not in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
            for state in previous
        ):
            raise PrerequisiteError("all preceding pipeline stages must succeed or be skipped")

        state = run.stages[index]
        attempt = StageAttempt(
            number=len(state.attempts) + 1,
            status=StageStatus.RUNNING,
            started_at=self._clock.now(),
        )
        running_state = replace(
            state, status=StageStatus.RUNNING, attempts=(*state.attempts, attempt)
        )
        run = self._replace_state(run, index, running_state)
        self._repository.save(run)
        self._publish(run, running_state, "stage started")

        handler = self._handlers[state.stage]
        try:
            outcome = handler.execute(PipelineExecutionContext(run.id, run.case_id))
        except Exception as error:
            failed_attempt = replace(
                attempt,
                status=StageStatus.FAILED,
                finished_at=self._clock.now(),
                error_code=type(error).__name__,
                error_message=str(error),
            )
            failed_state = replace(
                running_state,
                status=StageStatus.FAILED,
                attempts=(*running_state.attempts[:-1], failed_attempt),
            )
            run = self._replace_state(run, index, failed_state)
            self._repository.save(run)
            self._publish(run, failed_state, str(error))
            return run

        succeeded_attempt = replace(
            attempt,
            status=StageStatus.SUCCEEDED,
            finished_at=self._clock.now(),
            item_count=outcome.item_count,
        )
        succeeded_state = replace(
            running_state,
            status=StageStatus.SUCCEEDED,
            attempts=(*running_state.attempts[:-1], succeeded_attempt),
        )
        run = self._replace_state(run, index, succeeded_state)
        self._repository.save(run)
        self._publish(run, succeeded_state, outcome.message or "stage completed")
        return run

    def run_all(self, run_id: str) -> PipelineRun:
        run = self._require_run(run_id)
        while not run.stopped:
            run = self.run_next(run.id)
        return run

    def request_cancel(self, run_id: str) -> PipelineRun:
        run = self._require_run(run_id)
        if run.stopped:
            return run
        updated = replace(run, cancel_requested=True)
        self._repository.save(updated)
        return updated

    def retry_failed(self, run_id: str) -> PipelineRun:
        run = self._require_run(run_id)
        failed_index = next(
            (i for i, state in enumerate(run.stages) if state.status is StageStatus.FAILED),
            None,
        )
        if failed_index is None:
            raise PrerequisiteError("pipeline has no failed stage to retry")
        failed = run.stages[failed_index]
        if not self._handlers[failed.stage].retryable:
            raise PrerequisiteError(f"stage is not safe to retry: {failed.stage.value}")
        pending = replace(failed, status=StageStatus.PENDING)
        updated = self._replace_state(run, failed_index, pending)
        self._repository.save(updated)
        return updated

    def _cancel_pending(self, run: PipelineRun) -> PipelineRun:
        states = tuple(
            replace(state, status=StageStatus.CANCELLED)
            if state.status is StageStatus.PENDING
            else state
            for state in run.stages
        )
        updated = replace(run, stages=states)
        self._repository.save(updated)
        for state in states:
            if state.status is StageStatus.CANCELLED:
                self._publish(updated, state, "cancelled before execution")
        return updated

    def _require_run(self, run_id: str) -> PipelineRun:
        run = self._repository.get(run_id)
        if run is None:
            raise NotFoundError(f"pipeline run not found: {run_id}")
        return run

    @staticmethod
    def _replace_state(run: PipelineRun, index: int, state: StageState) -> PipelineRun:
        states = list(run.stages)
        states[index] = state
        return replace(run, stages=tuple(states))

    def _publish(self, run: PipelineRun, state: StageState, message: str) -> None:
        complete = sum(
            entry.status in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
            for entry in run.stages
        )
        self._publisher.publish(
            PipelineProgress(
                run.id,
                run.case_id,
                state.stage,
                state.status,
                complete,
                len(run.stages),
                message,
            )
        )
