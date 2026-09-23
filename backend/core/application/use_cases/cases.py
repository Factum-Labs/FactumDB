from __future__ import annotations

from core.application.models import Case, CreateCaseRequest, CreateCaseResponse
from core.application.ports import CaseRepository, CaseWorkspace, Clock, IdGenerator


class CreateCaseUseCase:
    """Create the workspace and persist one new case as a single application action."""

    def __init__(
        self,
        cases: CaseRepository,
        workspaces: CaseWorkspace,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._cases = cases
        self._workspaces = workspaces
        self._ids = ids
        self._clock = clock

    def execute(self, request: CreateCaseRequest) -> CreateCaseResponse:
        # Constructing Case performs the authoritative validation. Generate the id
        # first, but do not touch the filesystem until all user input is known valid.
        case_id = self._ids.new_id()
        name = request.name.strip()
        examiner = request.examiner.strip()
        if not name:
            raise ValueError("case name must not be empty")
        if not examiner:
            raise ValueError("examiner must not be empty")

        workspace_path = self._workspaces.create(case_id)
        try:
            case = Case(case_id, name, examiner, self._clock.now(), workspace_path)
            self._cases.save(case)
        except Exception:
            self._workspaces.discard(workspace_path)
            raise
        return CreateCaseResponse(case)
