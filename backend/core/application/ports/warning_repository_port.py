"""Port for the warnings the adapters raise."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.models.canonical import AnalysisWarning


class WarningRepositoryPort(ABC):
    """Stores the things an adapter could not handle.

    Backs the `warnings` table in docs/sqlite-schema.md section 11.

    These are stored rather than logged because they have to reach the final
    report. If an adapter quietly skipped a column or a whole event, the
    investigator needs to be told, because it changes how far the conclusion
    can be trusted. A warning that only ever went to stdout is a warning
    nobody will see.
    """

    @abstractmethod
    def save_many(self, warnings: Sequence[AnalysisWarning], case_id: str,
                  evidence_id: Optional[str] = None,
                  tool_run_id: Optional[str] = None) -> None:
        """Save warnings from one stage.

        evidence_id and tool_run_id are optional because not every warning is
        about one particular file or one particular command - some are about
        the case as a whole, such as evidence coming from an unvalidated MySQL
        version.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_case(self, case_id: str) -> Sequence[AnalysisWarning]:
        """Every warning raised in one case."""
        raise NotImplementedError

    @abstractmethod
    def list_by_code(self, case_id: str, code: str) -> Sequence[AnalysisWarning]:
        """Warnings of one kind, for example UNSUPPORTED_DATA_TYPE.

        The code column is indexed because the report groups warnings by kind
        rather than listing them in the order they happened.
        """
        raise NotImplementedError
