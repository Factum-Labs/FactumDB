"""Port for the record of every external tool we ran.

This is the provenance spine. Almost every other table stores a tool_run_id, so
any value that ends up in a report can be traced back to the command that
produced it.
"""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.models.canonical import ProvenanceReference, EventRef
from core.domain.models.evidence import ToolRun


class ToolRunRepositoryPort(ABC):
    """Stores one row per external tool invocation.

    Backs the `tool_runs` table in docs/sqlite-schema.md section 3, and
    provides `provenance_for`, which is part of the domain layer's
    EvidenceContext protocol in core/domain/ports.py.
    """

    @abstractmethod
    def save(self, run: ToolRun) -> None:
        """Persist one tool run, including its command and exit code."""
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, tool_run_id: str) -> Optional[ToolRun]:
        """Return one tool run, or None if there is no such run."""
        raise NotImplementedError

    @abstractmethod
    def list_by_evidence(self, evidence_id: str) -> Sequence[ToolRun]:
        """Every tool run against one evidence file, oldest first.

        This is what the UI shows on an evidence file's detail view: which
        tools have been run against it and whether they succeeded.
        """
        raise NotImplementedError

    @abstractmethod
    def provenance_for(self, ref: EventRef) -> Optional[ProvenanceReference]:
        """Which tool run produced the event at this position.

        Part of the domain layer's EvidenceContext protocol. EventRef is
        (source_file, log_position), which is why the lookup goes through the
        binlog event rather than being a direct key on tool_runs.

        Returns None when the event exists but no provenance was recorded for
        it, which is different from the event not existing.
        """
        raise NotImplementedError
