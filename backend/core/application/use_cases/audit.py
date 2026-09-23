from __future__ import annotations

from dataclasses import replace

from core.application.errors import NotFoundError, PrerequisiteError
from core.application.models import (
    CompleteToolRunRequest,
    StartToolRunRequest,
    ToolRun,
    ToolRunStatus,
    VerificationStatus,
)
from core.application.ports import (
    CaseRepository,
    Clock,
    EvidenceRepository,
    FileHasher,
    IdGenerator,
    RawOutputStore,
    ToolRunRepository,
)


class ToolRunAuditService:
    """Records reproducible utility invocation metadata and exact output bytes."""

    def __init__(
        self,
        cases: CaseRepository,
        evidence: EvidenceRepository,
        runs: ToolRunRepository,
        outputs: RawOutputStore,
        hasher: FileHasher,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._cases = cases
        self._evidence = evidence
        self._runs = runs
        self._outputs = outputs
        self._hasher = hasher
        self._ids = ids
        self._clock = clock

    def start(self, request: StartToolRunRequest) -> ToolRun:
        if self._cases.get(request.case_id) is None:
            raise NotFoundError(f"case not found: {request.case_id}")
        evidence = self._evidence.get(request.case_id, request.evidence_id)
        if evidence is None:
            raise NotFoundError(f"evidence not found: {request.evidence_id}")
        if evidence.verification_status is not VerificationStatus.VERIFIED:
            raise PrerequisiteError("tools may run only against verified evidence")
        run = ToolRun(
            id=self._ids.new_id(),
            case_id=request.case_id,
            evidence_id=request.evidence_id,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            executable_path=request.executable_path,
            executable_sha256=self._hasher.sha256(request.executable_path),
            arguments=request.arguments,
            started_at=self._clock.now(),
        )
        self._runs.save(run)
        return run

    def complete(self, request: CompleteToolRunRequest) -> ToolRun:
        run = self._runs.get(request.run_id)
        if run is None:
            raise NotFoundError(f"tool run not found: {request.run_id}")
        if run.status is not ToolRunStatus.RUNNING:
            raise PrerequisiteError(f"tool run is already complete: {request.run_id}")
        case = self._cases.get(run.case_id)
        if case is None:
            raise NotFoundError(f"case not found: {run.case_id}")
        stdout = self._outputs.save(case, run.id, "stdout", request.stdout)
        stderr = self._outputs.save(case, run.id, "stderr", request.stderr)
        completed = replace(
            run,
            status=(
                ToolRunStatus.SUCCEEDED if request.exit_code == 0 else ToolRunStatus.FAILED
            ),
            finished_at=self._clock.now(),
            exit_code=request.exit_code,
            stdout=stdout,
            stderr=stderr,
        )
        self._runs.save(completed)
        return completed
