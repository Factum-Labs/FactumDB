"""SQLite implementation of the integrity repository.

Stores what innochecksum said about each .ibd file. There is one result per
evidence file: checking the same file again replaces the old result instead
of adding a second one, because two stored answers for one file would leave
the report to guess which is current.

innochecksum knows about pages, not tables, so this table has no table name.
integrity_for(database, table) gets from a table to its file by joining
through schemas on evidence_id - the schema extracted from an .ibd is what
says which table that file holds.
"""

import json
from typing import Optional, Sequence

from adapters.persistence._transactions import transaction
from core.application.ports.integrity_repository_port import IntegrityRepositoryPort
from core.domain.models.canonical import IntegrityResult

_COLUMNS = """
    integrity_id, evidence_id, tool_run_id, total_pages, damaged_pages,
    status, page_counts_json, raw_summary
"""


class SqliteIntegrityRepository(IntegrityRepositoryPort):
    """Stores page validation results."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, result: IntegrityResult, evidence_id: str, tool_run_id: str) -> None:
        """Store one check, replacing any earlier check of the same file.

        page_counts is stored whole, zeros included. "Undo log page: 0" is the
        reason an earlier value cannot be recovered from the file, so a zero
        here is a finding, not noise.
        """
        with transaction(self._connection):
            self._connection.execute(
                "DELETE FROM integrity_results WHERE evidence_id = ?", (evidence_id,)
            )
            self._connection.execute(
                f"INSERT INTO integrity_results ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{evidence_id}:integrity",
                    evidence_id,
                    tool_run_id,
                    result.total_pages,
                    result.damaged_pages,
                    result.status,
                    json.dumps(dict(result.page_counts)),
                    result.raw_summary,
                ),
            )

    def integrity_for(self, database: str, table: str) -> Optional[IntegrityResult]:
        """The check for the file holding this table, or None.

        None means there is no checked .ibd for the table - either none was
        seized, or its schema has not been extracted yet so the file cannot be
        matched to a table. Neither is the same as the file being damaged.

        If one table was seized more than once, the most recently stored
        schema decides which file is used, the same rule schema_for() uses.
        """
        row = self._connection.execute(
            f"""
            SELECT {_prefixed('i')} FROM integrity_results i
            JOIN schemas s ON s.evidence_id = i.evidence_id
            WHERE s.database_name = ? AND s.table_name = ?
            ORDER BY s.rowid DESC
            LIMIT 1
            """,
            (database, table),
        ).fetchone()
        return _row_to_result(row) if row is not None else None

    def find_by_evidence(self, evidence_id: str) -> Optional[IntegrityResult]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM integrity_results WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        return _row_to_result(row) if row is not None else None

    def list_damaged(self, case_id: str) -> Sequence[IntegrityResult]:
        """Every file in the case that innochecksum found damaged pages in.

        'unknown' is not included. It means the summary could not be read, not
        that a page failed, and the report should say that differently.
        """
        rows = self._connection.execute(
            f"""
            SELECT {_prefixed('i')} FROM integrity_results i
            JOIN evidence_files e ON e.evidence_id = i.evidence_id
            WHERE e.case_id = ? AND i.status = 'damaged'
            ORDER BY e.filename
            """,
            (case_id,),
        ).fetchall()
        return [_row_to_result(r) for r in rows]


def _row_to_result(row) -> IntegrityResult:
    return IntegrityResult(
        total_pages=row["total_pages"],
        damaged_pages=row["damaged_pages"],
        status=row["status"],
        page_counts=json.loads(row["page_counts_json"]) if row["page_counts_json"] else {},
        raw_summary=row["raw_summary"] or "",
    )


def _prefixed(alias: str) -> str:
    return ", ".join(f"{alias}.{c.strip()}" for c in _COLUMNS.split(","))
