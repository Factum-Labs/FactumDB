"""Port for the transaction markers found in the binary logs."""

from abc import ABC, abstractmethod
from typing import Sequence

from core.domain.models.canonical import TransactionMarker


class TransactionRepositoryPort(ABC):
    """Stores which events were committed together.

    Backs the `transactions` and `transaction_events` tables in
    docs/sqlite-schema.md sections 8 and 9.

    `markers` is the other half of the domain layer's EventSource protocol.
    The adapter only records the markers it can actually see in the log -
    BEGIN, Xid, COMMIT, ROLLBACK. Deciding what a grouping means is the
    TransactionGroupingService's job, not this layer's.
    """

    @abstractmethod
    def save_many(self, markers: Sequence[TransactionMarker],
                  evidence_id: str, tool_run_id: str) -> None:
        """Save a batch of markers and their links to events.

        Each marker carries event_positions, a list of log positions. Those
        become rows in transaction_events rather than a JSON array, so the
        link is a real foreign key that the database checks. A JSON array of
        numbers could point at events that do not exist and nothing would
        notice.
        """
        raise NotImplementedError

    @abstractmethod
    def markers(self) -> Sequence[TransactionMarker]:
        """Every transaction marker in the case.

        EventSource.markers.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_evidence(self, evidence_id: str) -> Sequence[TransactionMarker]:
        """Markers from one evidence file only."""
        raise NotImplementedError

    @abstractmethod
    def list_incomplete(self, case_id: str) -> Sequence[TransactionMarker]:
        """Transactions that start but never commit or roll back.

        These are evidence gaps, not noise. A transaction left open because
        the binlog we were given ends in the middle of it is exactly the kind
        of thing that has to reach the report rather than being dropped.
        """
        raise NotImplementedError
