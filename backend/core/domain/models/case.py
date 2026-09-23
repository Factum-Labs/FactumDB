"""Canonical case model for application and persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.domain.models._validation import _required


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    name: str
    examiner: str
    created_at: datetime
    workspace_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "case id"))
        object.__setattr__(self, "name", _required(self.name, "case name"))
        object.__setattr__(self, "examiner", _required(self.examiner, "examiner"))
        object.__setattr__(
            self, "workspace_path", _required(self.workspace_path, "workspace path")
        )
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


    @property
    def case_id(self) -> str:
        return self.id

    @property
    def case_name(self) -> str:
        return self.name

    @classmethod
    def create(
        cls, case_name: str, examiner: str, *, case_id: str,
        created_at: datetime, workspace_path: str,
    ) -> Case:
        """Construct from metadata supplied by the application's ID and clock ports."""
        return cls(case_id, case_name, examiner, created_at, workspace_path)

