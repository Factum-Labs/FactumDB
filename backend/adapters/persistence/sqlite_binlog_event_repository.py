"""SQLite implementation of the binlog event repository.

Stores the row changes decoded out of the binary logs. Three things about
this table are easy to get wrong, and each one loses data quietly if it is.

Positions restart in every file. log_position is only unique inside one
binlog, because every new file starts again at 4. Any key or lookup that uses
a position has to carry the file with it.

One event can hold many rows. An UPDATE or DELETE whose WHERE matches several
rows, or a multi-row INSERT, is written as a single binlog event with several
row images, all sharing one end_log_pos. The adapter turns each row image into
its own BinlogEvent, so several of them arrive with the same file and
position. row_index - the order of a row image within its event - is what
keeps them apart. The adapter assigns it while decoding; the BinlogEvent model carries it
through persistence and analysis.

Writes are plain INSERTs, not INSERT OR REPLACE. If two rows ever did collide
on the unique key, INSERT OR REPLACE would let the second silently overwrite
the first - a row change would vanish from the evidence with no error at all.
A plain INSERT fails loudly instead. Re-running an extraction is handled by
deleting that file's rows first, which is explicit about what it replaces.

events() is half of the domain layer's EventSource protocol; markers() lives
on the transaction repository.
"""

from typing import Optional, Sequence

from adapters.persistence._in_case import in_case
from adapters.persistence._provenance import provenance_from
from adapters.persistence._timestamps import from_text, to_text
from adapters.persistence._values import from_json, to_json
from core.application.ports.binlog_event_repository_port import (
    BinlogEventRepositoryPort,
)
from core.domain.models.canonical import BinlogEvent, EventRef

_COLUMNS = """
    event_id, evidence_id, tool_run_id, event_type, database_name,
    table_name, before_json, after_json, event_time_utc, raw_timestamp,
    gtid, thread_id, source_file, log_position, row_index
"""

# Reads also fetch the name of the tool that produced each event, which its
# provenance needs (see _provenance.py).
_SELECT = (
    "SELECT " + ", ".join(f"b.{c.strip()}" for c in _COLUMNS.split(","))
    + ", t.tool_name FROM binlog_events b"
    " LEFT JOIN tool_runs t ON t.tool_run_id = b.tool_run_id"
)

# Timestamps in a binlog header are only accurate to the second, so several
# events regularly share one - all three in the deletion scenario did. The
# file, position and row index after it make the order the same on every run,
# and within one server's logs they are the order the events were written in.
_ORDER = "ORDER BY b.event_time_utc, b.source_file, b.log_position, b.row_index"


class SqliteBinlogEventRepository(BinlogEventRepositoryPort):
    """Stores decoded binlog row events."""

    def __init__(self, connection):
        self._connection = connection

    def save_many(self, events: Sequence[BinlogEvent],
                  evidence_id: str, tool_run_id: str) -> None:
        """Store one decoding run's worth of events.

        Existing rows for each binlog file in the batch are deleted first, so
        decoding the same file again replaces its events rather than adding
        a second copy of them.
        """
        if not events:
            return

        rows = []
        for event in events:
            row_index = event.row_index
            rows.append(
                (
                    _event_id(evidence_id, event.source_file, event.log_position, row_index),
                    evidence_id,
                    tool_run_id,
                    event.event_type,
                    event.database,
                    event.table,
                    to_json(event.before) if event.before is not None else None,
                    to_json(event.after) if event.after is not None else None,
                    to_text(event.timestamp),
                    event.raw_timestamp,
                    event.gtid,
                    event.thread_id,
                    event.source_file,
                    event.log_position,
                    row_index,
                )
            )

        files = {event.source_file for event in events}

        with self._connection:
            for source_file in files:
                # Transactions link to these events, and the foreign key
                # would block the delete. The links go too; saving the
                # markers again afterwards puts them back.
                self._connection.execute(
                    """
                    DELETE FROM transaction_events WHERE event_id IN (
                        SELECT event_id FROM binlog_events
                        WHERE evidence_id = ? AND source_file = ?)
                    """,
                    (evidence_id, source_file),
                )
                self._connection.execute(
                    "DELETE FROM binlog_events WHERE evidence_id = ? AND source_file = ?",
                    (evidence_id, source_file),
                )
            self._connection.executemany(
                f"INSERT INTO binlog_events ({_COLUMNS}) "
                "VALUES (" + ", ".join(["?"] * 15) + ")",
                rows,
            )

    def events(self, *, case_id: Optional[str] = None) -> Sequence[BinlogEvent]:
        """Every decoded event in the case, in time order.

        Time rather than position, because a position only orders events
        inside one file and a case normally has several files.
        """
        condition, args = in_case(case_id, "b.evidence_id")
        rows = self._connection.execute(f"{_SELECT} WHERE {condition} {_ORDER}", args).fetchall()
        return [_row_to_event(r) for r in rows]

    def list_by_table(self, database: str, table: str) -> Sequence[BinlogEvent]:
        """Events affecting one table only.

        Filtered in SQL rather than by loading everything and filtering in
        Python - that is the reason (database_name, table_name) is indexed.
        """
        rows = self._connection.execute(
            f"{_SELECT} WHERE b.database_name = ? AND b.table_name = ? {_ORDER}",
            (database, table),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def find_by_ref(self, evidence_id: str, ref: EventRef) -> Optional[BinlogEvent]:
        """One row by (source_file, log_position, row_index), or None."""
        source_file, log_position = ref[:2]
        row = self._connection.execute(
            f"{_SELECT} WHERE b.evidence_id = ? AND b.source_file = ? AND b.log_position = ? "
            "AND b.row_index = ?",
            (evidence_id, source_file, log_position, ref[2]),
        ).fetchone()
        return _row_to_event(row) if row is not None else None

    def rows_in_event(self, evidence_id: str, ref: EventRef) -> Sequence[BinlogEvent]:
        """Every row image that one binlog event carried, in order.

        The row component is ignored deliberately: this convenience lookup
        requests the entire event, whereas find_by_ref names one specific row.
        """
        source_file, log_position = ref[:2]
        rows = self._connection.execute(
            f"{_SELECT} WHERE b.evidence_id = ? AND b.source_file = ? AND b.log_position = ? "
            "ORDER BY b.row_index",
            (evidence_id, source_file, log_position),
        ).fetchall()
        return [_row_to_event(r) for r in rows]


def _event_id(evidence_id: str, source_file: str, log_position: int, row_index: int) -> str:
    """Readable, and the same every time the same file is decoded."""
    return f"{evidence_id}:{source_file}@{log_position}#{row_index}"


def _row_to_event(row) -> BinlogEvent:
    return BinlogEvent(
        event_type=row["event_type"],
        database=row["database_name"],
        table=row["table_name"],
        before=from_json(row["before_json"]) if row["before_json"] is not None else None,
        after=from_json(row["after_json"]) if row["after_json"] is not None else None,
        timestamp=from_text(row["event_time_utc"]),
        raw_timestamp=row["raw_timestamp"],
        log_position=row["log_position"],
        source_file=row["source_file"],
        gtid=row["gtid"],
        thread_id=row["thread_id"],
        row_index=row["row_index"],
        provenance=provenance_from(row, row["source_file"], row["log_position"], row["row_index"]),
    )
