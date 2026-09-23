"""Port for the row changes decoded out of the binary logs."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.models.canonical import BinlogEvent, EventRef


class BinlogEventRepositoryPort(ABC):
    """Stores decoded row events and serves them to the domain layer.

    Backs the `binlog_events` table in docs/sqlite-schema.md section 7.

    `events` is half of the domain layer's EventSource protocol; the other
    half, `markers`, lives on TransactionRepositoryPort.

    One thing to be careful about in any implementation: log_position is only
    unique inside a single binlog file, because positions restart at 4 in each
    new file. The unique key is (evidence_id, source_file, log_position), and
    any lookup by position has to carry the file with it.
    """

    @abstractmethod
    def save_many(self, events: Sequence[BinlogEvent],
                  evidence_id: str, tool_run_id: str) -> None:
        """Save a batch of decoded events from one tool run.

        A single binlog can contain thousands of row events, so this is
        batched for the same reasons as the physical records.
        """
        raise NotImplementedError

    @abstractmethod
    def events(self) -> Sequence[BinlogEvent]:
        """Every decoded event in the case, in timestamp order.

        EventSource.events. Ordered by time rather than by log position
        because positions only order events within one file, and a case
        normally has several.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_table(self, database: str, table: str) -> Sequence[BinlogEvent]:
        """Events affecting one table only, in timestamp order.

        This is the table filtering the plan asks for. Doing it in SQL rather
        than loading everything and filtering in Python is the whole reason
        (database_name, table_name) is indexed.
        """
        raise NotImplementedError

    @abstractmethod
    def find_by_ref(self, evidence_id: str, ref: EventRef) -> Optional[BinlogEvent]:
        """One event by its (source_file, log_position), or None.

        evidence_id is required as well because EventRef alone is not unique
        across evidence sets.
        """
        raise NotImplementedError
