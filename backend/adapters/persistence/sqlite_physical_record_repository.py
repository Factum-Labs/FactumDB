"""SQLite implementation of the physical record repository.

Stores the rows unloaded from a tablespace, both the live ones and the
deleted remnants ibd2sql recovers with --delete only. Deleted rows are kept
in the same table with a flag rather than in a table of their own, because a
deleted row is still a row on the page - InnoDB itself marks deletion with a
single flag bit in the record header.

Rows are written in batches. A real tablespace holds thousands of them, and
inserting one at a time means a separate transaction each. One executemany
inside one transaction is much faster and is also atomic: either a whole
extraction is stored or none of it is, which matters when the alternative is
a half-populated table that looks complete.

records_for() and tables_with_physical_evidence() are domain layer protocol
methods, so this class can be passed straight to the reconciliation service.
"""

from typing import FrozenSet, Sequence, Tuple

from adapters.persistence._values import from_json, to_json
from core.application.ports.physical_record_repository_port import (
    PhysicalRecordRepositoryPort,
)
from core.domain.models.canonical import PhysicalRecord

_COLUMNS = """
    record_id, evidence_id, tool_run_id, database_name, table_name,
    values_json, is_deleted, page_no, page_offset
"""


class SqlitePhysicalRecordRepository(PhysicalRecordRepositoryPort):
    """Stores rows read out of the .ibd files."""

    def __init__(self, connection):
        self._connection = connection

    def save_many(self, records: Sequence[PhysicalRecord],
                  evidence_id: str, tool_run_id: str) -> None:
        """Store one extraction's worth of rows.

        Rows are replaced per (table, live-or-deleted) group rather than
        appended, so running the extraction twice does not double the rows.
        The two groups are kept apart because the live rows and the deleted
        rows come from two separate ibd2sql runs, and saving the second must
        not wipe the first.
        """
        if not records:
            return

        groups = {(r.database, r.table, r.is_deleted) for r in records}
        counters = {group: 0 for group in groups}
        rows = []

        for record in records:
            group = (record.database, record.table, record.is_deleted)
            index = counters[group]
            counters[group] = index + 1
            rows.append(
                (
                    _record_id(evidence_id, record, index),
                    evidence_id,
                    tool_run_id,
                    record.database,
                    record.table,
                    to_json(record.values),
                    int(record.is_deleted),
                    record.page_no,
                    record.page_offset,
                )
            )

        with self._connection:
            for database, table, is_deleted in groups:
                self._connection.execute(
                    """
                    DELETE FROM physical_records
                    WHERE evidence_id = ? AND database_name = ?
                      AND table_name = ? AND is_deleted = ?
                    """,
                    (evidence_id, database, table, int(is_deleted)),
                )
            self._connection.executemany(
                f"INSERT INTO physical_records ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def records_for(self, database: str, table: str) -> Sequence[PhysicalRecord]:
        """Every row for one table, deleted ones included.

        Deleted rows are included on purpose: a row that survives only as a
        deleted remnant is a finding, not noise, and the reconciliation
        service needs to see it to say so.
        """
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM physical_records "
            "WHERE database_name = ? AND table_name = ? ORDER BY record_id",
            (database, table),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def list_deleted(self, case_id: str) -> Sequence[PhysicalRecord]:
        """Only the recovered deleted rows, across a whole case.

        physical_records has no case_id of its own - a row belongs to an
        evidence file, and the evidence file belongs to a case - so this
        joins through evidence_files rather than duplicating the column.
        """
        rows = self._connection.execute(
            """
            SELECT p.record_id, p.evidence_id, p.tool_run_id, p.database_name,
                   p.table_name, p.values_json, p.is_deleted, p.page_no, p.page_offset
            FROM physical_records p
            JOIN evidence_files e ON e.evidence_id = p.evidence_id
            WHERE e.case_id = ? AND p.is_deleted = 1
            ORDER BY p.database_name, p.table_name, p.record_id
            """,
            (case_id,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def tables_with_physical_evidence(self) -> FrozenSet[Tuple[str, str]]:
        """Every (database, table) a tablespace was actually seized for.

        This is what lets the reconciliation service tell two very different
        situations apart: a row missing because it was deleted, and a row
        missing because nobody seized that table's .ibd. Without it "not
        found" would collapse both into one answer, and the tool could report
        a deletion that never happened.
        """
        rows = self._connection.execute(
            "SELECT DISTINCT database_name, table_name FROM physical_records"
        ).fetchall()
        return frozenset((r["database_name"], r["table_name"]) for r in rows)


def _record_id(evidence_id: str, record: PhysicalRecord, index: int) -> str:
    """A readable id that is the same every time the extraction is re-run.

    A physical row has no natural key we can rely on - the primary key is
    inside values, and a deleted remnant may not have a usable one at all -
    so the position within its group is used. ibd2sql walks the page in a
    fixed order, so the same evidence produces the same ids.
    """
    kind = "deleted" if record.is_deleted else "live"
    return f"{evidence_id}:{record.database}.{record.table}:{kind}#{index}"


def _row_to_record(row) -> PhysicalRecord:
    return PhysicalRecord(
        database=row["database_name"],
        table=row["table_name"],
        values=from_json(row["values_json"]),
        is_deleted=bool(row["is_deleted"]),
        page_no=row["page_no"],
        page_offset=row["page_offset"],
    )
