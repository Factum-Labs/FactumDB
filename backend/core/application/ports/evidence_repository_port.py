"""Port for storing the evidence files registered in a case."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.models.evidence import EvidenceFile


class EvidenceRepositoryPort(ABC):
    """Stores the files that were seized, and their hashes.

    Backs the `evidence_files` table in docs/sqlite-schema.md section 2.
    """

    @abstractmethod
    def save(self, evidence: EvidenceFile) -> None:
        """Persist one registered evidence file."""
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, evidence_id: str) -> Optional[EvidenceFile]:
        """Return one evidence file, or None if it is not registered."""
        raise NotImplementedError

    @abstractmethod
    def list_by_case(self, case_id: str) -> Sequence[EvidenceFile]:
        """Every evidence file registered in one case."""
        raise NotImplementedError

    @abstractmethod
    def list_by_type(self, case_id: str, evidence_type: str) -> Sequence[EvidenceFile]:
        """Evidence of one kind only - "ibd", "binlog" or "binlog_index".

        The binlog decoding stage only wants the binlogs, and the schema
        extraction stage only wants the .ibd files, so this saves both of them
        filtering the whole list themselves.
        """
        raise NotImplementedError
