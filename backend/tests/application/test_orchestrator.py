from __future__ import annotations

import unittest

from core.application.errors import ConflictError, PrerequisiteError
from core.application.models import Case
from core.application.orchestration.models import (
    PipelineExecutionContext,
    PipelineProgress,
    PipelineRun,
    PipelineStage,
    StageOutcome,
    StageStatus,
)
from core.application.orchestration.pipeline import AnalysisOrchestrator
from tests.application.fakes import FIXED_NOW, FixedClock, FixedIds, MemoryCases


STAGES = (
    PipelineStage.VERIFY_EVIDENCE,
    PipelineStage.VALIDATE_PAGES,
    PipelineStage.EXTRACT_SCHEMA,
)


class MemoryPipelines:
    def __init__(self) -> None:
        self.runs: dict[str, PipelineRun] = {}

    def save(self, run: PipelineRun) -> None:
        self.runs[run.id] = run

    def get(self, run_id: str) -> PipelineRun | None:
        return self.runs.get(run_id)

    def active_for_case(self, case_id: str) -> PipelineRun | None:
        return next(
            (run for run in self.runs.values() if run.case_id == case_id and not run.stopped),
            None,
        )


class MemoryPublisher:
    def __init__(self) -> None:
        self.events: list[PipelineProgress] = []

    def publish(self, progress: PipelineProgress) -> None:
        self.events.append(progress)


class Handler:
    def __init__(
        self,
        stage: PipelineStage,
        *,
        retryable: bool = True,
        failures: int = 0,
    ) -> None:
        self._stage = stage
        self._retryable = retryable
        self.failures = failures
        self.calls: list[PipelineExecutionContext] = []

    @property
    def stage(self) -> PipelineStage:
        return self._stage

    @property
    def retryable(self) -> bool:
        return self._retryable

    def execute(self, context: PipelineExecutionContext) -> StageOutcome:
        self.calls.append(context)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("controlled failure")
        return StageOutcome(item_count=1, message=f"{self.stage.value} complete")


def a_case() -> Case:
    return Case("case-1", "Investigation", "Nisal", FIXED_NOW, "/workspace/case-1")


def orchestrator(
    handlers: tuple[Handler, ...] | None = None,
) -> tuple[AnalysisOrchestrator, MemoryPipelines, MemoryPublisher, tuple[Handler, ...]]:
    configured = handlers or tuple(Handler(stage) for stage in STAGES)
    repository = MemoryPipelines()
    publisher = MemoryPublisher()
    service = AnalysisOrchestrator(
        MemoryCases(a_case()),
        repository,
        publisher,
        configured,
        FixedIds("run-1"),
        FixedClock(),
        STAGES,
    )
    return service, repository, publisher, configured


class OrchestratorTests(unittest.TestCase):
    def test_run_all_executes_handlers_in_order_and_persists_attempts(self) -> None:
        service, repository, publisher, handlers = orchestrator()
        run = service.run_all(service.start("case-1").id)

        self.assertTrue(run.complete)
        self.assertEqual([len(handler.calls) for handler in handlers], [1, 1, 1])
        self.assertTrue(
            all(state.attempts[0].status is StageStatus.SUCCEEDED for state in run.stages)
        )
        self.assertEqual(len(publisher.events), len(STAGES) * 2)
        self.assertIs(repository.get(run.id), run)

    def test_start_prevents_two_active_runs_for_one_case(self) -> None:
        service, _, _, _ = orchestrator()
        service.start("case-1")
        with self.assertRaises(ConflictError):
            service.start("case-1")

    def test_failure_stops_pipeline_and_records_sanitized_error(self) -> None:
        handlers = (
            Handler(STAGES[0]),
            Handler(STAGES[1], failures=1),
            Handler(STAGES[2]),
        )
        service, _, _, _ = orchestrator(handlers)
        run = service.run_all(service.start("case-1").id)

        failed = run.state_for(STAGES[1])
        self.assertEqual(failed.status, StageStatus.FAILED)
        self.assertEqual(failed.attempts[-1].error_code, "RuntimeError")
        self.assertEqual(failed.attempts[-1].error_message, "controlled failure")
        self.assertEqual(run.state_for(STAGES[2]).status, StageStatus.PENDING)

    def test_retry_retains_failed_attempt_and_then_completes(self) -> None:
        handlers = (
            Handler(STAGES[0]),
            Handler(STAGES[1], failures=1),
            Handler(STAGES[2]),
        )
        service, _, _, _ = orchestrator(handlers)
        failed = service.run_all(service.start("case-1").id)
        service.retry_failed(failed.id)
        completed = service.run_all(failed.id)

        attempts = completed.state_for(STAGES[1]).attempts
        self.assertEqual([attempt.status for attempt in attempts], [
            StageStatus.FAILED,
            StageStatus.SUCCEEDED,
        ])
        self.assertTrue(completed.complete)

    def test_non_retryable_failure_is_rejected(self) -> None:
        handlers = (
            Handler(STAGES[0], retryable=False, failures=1),
            Handler(STAGES[1]),
            Handler(STAGES[2]),
        )
        service, _, _, _ = orchestrator(handlers)
        failed = service.run_all(service.start("case-1").id)
        with self.assertRaisesRegex(PrerequisiteError, "not safe"):
            service.retry_failed(failed.id)

    def test_cancellation_marks_every_pending_stage(self) -> None:
        service, _, publisher, _ = orchestrator()
        run = service.start("case-1")
        service.request_cancel(run.id)
        cancelled = service.run_next(run.id)

        self.assertTrue(all(s.status is StageStatus.CANCELLED for s in cancelled.stages))
        self.assertEqual(len(publisher.events), len(STAGES))


if __name__ == "__main__":
    unittest.main()
