"""SQLite implementation of the transaction repository.

Stores the BEGIN / COMMIT / ROLLBACK markers the binlog adapter saw, and which
events each one wrapped. The events themselves live in binlog_events; this
table only records how they were grouped.

A marker lists its events by log position. Those positions become rows in
transaction_events that point at real binlog_events rows, so the database
checks that every event a transaction claims actually exists. That means the
events of a file have to be saved before its markers.

One position can be several rows, because a multi-row UPDATE or DELETE is a
single binlog event with several row images (see row_index in the binlog
event repository). Every row at a position is linked to the transaction, and
they share that position's event_order. Reading a marker back takes each
position once, so event_positions comes back the same as it went in.

markers() is the other half of the domain layer's EventSource protocol;
events() is on the binlog event repository.
"""

from typing import Sequence

from adapters.persistence._provenance import provenance_from
from core.application.ports.transaction_repository_port import (
    TransactionRepositoryPort,
)
from core.domain.models.canonical import TransactionMarker

_COLUMNS = """
    transaction_id, evidence_id, tool_run_id, gtid, xid, thread_id,
    status, source_file, start_position, end_position
"""

# Reads also fetch the name of the tool that saw each marker, which its
# provenance needs (see _provenance.py).
_SELECT = (
    "SELECT " + ", ".join(f"t.{c.strip()}" for c in _COLUMNS.split(","))
    + ", r.tool_name FROM transactions t"
    " LEFT JOIN tool_runs r ON r.tool_run_id = t.tool_run_id"
)

_ORDER = "ORDER BY t.source_file, t.start_position"


class SqliteTransactionRepository(TransactionRepositoryPort):
    """Stores transaction markers and their links to events."""

    def __init__(self, connection):
        self._connection = connection

    def save_many(self, markers: Sequence[TransactionMarker],
                  evidence_id: str, tool_run_id: str) -> None:
        """Store one decoding run's markers.

        Like the events, markers are replaced per binlog file, so decoding a
        file again does not leave two copies of every transaction.

        A position with no stored event makes the whole batch fail with an
        IntegrityError. A transaction that claims an event we do not have is
        a gap in the evidence, and that should stop the save rather than be
        stored as a link to nothing.
        """
        if not markers:
            return

        files = {marker.source_file for marker in markers}

        with self._connection:
            for source_file in files:
                self._delete_file(evidence_id, source_file)

            for marker in markers:
                transaction_id = _transaction_id(
                    evidence_id, marker.source_file, marker.start_position
                )
                self._connection.execute(
                    f"INSERT INTO transactions ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        transaction_id,
                        evidence_id,
                        tool_run_id,
                        marker.gtid,
                        marker.xid,
                        marker.thread_id,
                        marker.status,
                        marker.source_file,
                        marker.start_position,
                        marker.end_position,
                    ),
                )
                self._link_events(transaction_id, evidence_id, marker)

    def markers(self) -> Sequence[TransactionMarker]:
        """Every transaction marker in the case, in log order."""
        rows = self._connection.execute(f"{_SELECT} {_ORDER}").fetchall()
        return [self._load(r) for r in rows]

    def list_by_evidence(self, evidence_id: str) -> Sequence[TransactionMarker]:
        rows = self._connection.execute(
            f"{_SELECT} WHERE t.evidence_id = ? {_ORDER}",
            (evidence_id,),
        ).fetchall()
        return [self._load(r) for r in rows]

    def list_incomplete(self, case_id: str) -> Sequence[TransactionMarker]:
        """Transactions with no COMMIT or ROLLBACK, across the whole case.

        transactions has no case_id of its own, so this joins through the
        evidence file, the same way list_deleted() does for physical rows.
        """
        rows = self._connection.execute(
            f"{_SELECT} JOIN evidence_files e ON e.evidence_id = t.evidence_id "
            f"WHERE e.case_id = ? AND t.status = 'incomplete' {_ORDER}",
            (case_id,),
        ).fetchall()
        return [self._load(r) for r in rows]

    def _link_events(self, transaction_id: str, evidence_id: str,
                     marker: TransactionMarker) -> None:
        for order, position in enumerate(marker.event_positions):
            event_ids = self._connection.execute(
                """
                SELECT event_id FROM binlog_events
                WHERE evidence_id = ? AND source_file = ? AND log_position = ?
                ORDER BY row_index
                """,
                (evidence_id, marker.source_file, position),
            ).fetchall()
            if not event_ids:
                # Checked here rather than left to the foreign key, because
                # there is no event_id to insert at all, and the error should
                # say which position was missing.
                raise LookupError(
                    f"transaction at {marker.source_file}@{marker.start_position} "
                    f"lists position {position}, but no event is stored there"
                )
            self._connection.executemany(
                "INSERT INTO transaction_events (transaction_id, event_id, event_order) "
                "VALUES (?, ?, ?)",
                [(transaction_id, row["event_id"], order) for row in event_ids],
            )

    def _delete_file(self, evidence_id: str, source_file: str) -> None:
        """Links first, because they point at the transactions."""
        self._connection.execute(
            """
            DELETE FROM transaction_events WHERE transaction_id IN (
                SELECT transaction_id FROM transactions
                WHERE evidence_id = ? AND source_file = ?)
            """,
            (evidence_id, source_file),
        )
        self._connection.execute(
            "DELETE FROM transactions WHERE evidence_id = ? AND source_file = ?",
            (evidence_id, source_file),
        )

    def _load(self, row) -> TransactionMarker:
        positions = self._connection.execute(
            """
            SELECT DISTINCT b.log_position, te.event_order
            FROM transaction_events te
            JOIN binlog_events b ON b.event_id = te.event_id
            WHERE te.transaction_id = ?
            ORDER BY te.event_order
            """,
            (row["transaction_id"],),
        ).fetchall()
        return TransactionMarker(
            status=row["status"],
            start_position=row["start_position"],
            end_position=row["end_position"],
            source_file=row["source_file"],
            event_positions=tuple(p["log_position"] for p in positions),
            gtid=row["gtid"],
            xid=row["xid"],
            thread_id=row["thread_id"],
            provenance=provenance_from(row, row["source_file"], row["start_position"]),
        )


def _transaction_id(evidence_id: str, source_file: str, start_position: int) -> str:
    """A transaction starts at one place in one file, so that names it."""
    return f"{evidence_id}:{source_file}@{start_position}"
