"""Port for the rows read out of the .ibd files."""

from abc import ABC, abstractmethod
from typing import FrozenSet, Sequence, Tuple

from core.domain.models.canonical import PhysicalRecord


class PhysicalRecordRepositoryPort(ABC):
    """Stores rows unloaded from a tablespace, live and deleted.

    Backs the `physical_records` table in docs/sqlite-schema.md section 6.

    `records_for` is the domain layer's PhysicalRecordSource protocol, so an
    implementation can be handed straight to the reconciliation service.
    """

    @abstractmethod
    def save_many(self, records: Sequence[PhysicalRecord],
                  evidence_id: str, tool_run_id: str) -> None:
        """Save a batch of rows from one tool run.

        Batched rather than one at a time because a real tablespace holds
        thousands of rows, and inserting them individually means a separate
        transaction per row. One executemany inside one transaction is far
        faster and is also atomic: either the whole extraction is stored or
        none of it is, which matters when the alternative is a half-populated
        table that looks complete.
        """
        raise NotImplementedError

    @abstractmethod
    def records_for(self, database: str, table: str) -> Sequence[PhysicalRecord]:
        """Every physical row for one table, deleted ones included.

        PhysicalRecordSource.records_for. Deleted rows are included because
        the reconciliation service needs to see them - a row that exists only
        as a deleted remnant is a finding, not noise.
        """
        raise NotImplementedError

    @abstractmethod
    def list_deleted(self, case_id: str) -> Sequence[PhysicalRecord]:
        """Only the recovered deleted rows, across the whole case.

        This is its own method because it is one of the main things an
        investigator asks for, and it is the screen worth demonstrating.
        The is_deleted column is indexed for exactly this query.
        """
        raise NotImplementedError

    @abstractmethod
    def tables_with_physical_evidence(self) -> FrozenSet[Tuple[str, str]]:
        """Every (database, table) we actually hold a tablespace for.

        EvidenceContext.tables_with_physical_evidence. This is what lets the
        reconciliation service tell two very different situations apart: a row
        that is absent because it was deleted, and a row that is absent
        because nobody seized that table's .ibd in the first place. Without
        it, "not found" would collapse both into one answer and the tool would
        report a deletion that may never have happened.
        """
        raise NotImplementedError
