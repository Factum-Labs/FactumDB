"""Application request, response and transfer contracts."""

from dataclasses import dataclass
from core.domain.models.case import Case


@dataclass(frozen=True, slots=True)
class CreateCaseRequest:
    case_name: str
    examiner: str

    @property
    def name(self) -> str:
        return self.case_name


@dataclass(frozen=True, slots=True)
class CreateCaseResponse:
    case: Case

    @property
    def case_id(self) -> str:
        return self.case.id

    @property
    def case_name(self) -> str:
        return self.case.name

    @property
    def examiner(self) -> str:
        return self.case.examiner

    @property
    def created_at(self) -> str:
        return self.case.created_at.isoformat()
