"""Port for the innochecksum results."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.models.canonical import IntegrityResult


class IntegrityRepositoryPort(ABC):
    """Stores the physical condition of each tablespace.

    Backs the `integrity_results` table in docs/sqlite-schema.md section 10.

    `integrity_for` is part of the domain layer's EvidenceContext protocol.
    """

    @abstractmethod
    def save(self, result: IntegrityResult,
             evidence_id: str, tool_run_id: str) -> None:
        """Persist one integrity check.

        The whole page_counts mapping is stored, including the entries that
        are zero. An "Undo log page" count of 0 is the reason an earlier value
        cannot be recovered from a tablespace at all, so dropping zeros as
        noise would throw away a finding.
        """
        raise NotImplementedError

    @abstractmethod
    def integrity_for(self, database: str, table: str) -> Optional[IntegrityResult]:
        """The check for the tablespace backing this table, or None.

        EvidenceContext.integrity_for. None means no .ibd was registered for
        that table, which is different from the file being damaged.
        """
        raise NotImplementedError

    @abstractmethod
    def find_by_evidence(self, evidence_id: str) -> Optional[IntegrityResult]:
        """The check for one specific evidence file."""
        raise NotImplementedError

    @abstractmethod
    def list_damaged(self, case_id: str) -> Sequence[IntegrityResult]:
        """Every evidence file that failed validation.

        Anything here limits what the rest of the case can conclude, so the
        report needs it up front rather than buried per file.
        """
        raise NotImplementedError
