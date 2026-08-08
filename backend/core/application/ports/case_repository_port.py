from abc import ABC, abstractmethod
from typing import Optional

from core.domain.models.case import Case

class CaseRepositoryPort(ABC):

    @abstractmethod
    def save(self, case: Case) -> None:
        """Persist a case."""
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, case_id: str) -> Optional[Case]:
        """Return a case by ID, or None if it does not exist."""
        raise NotImplementedError