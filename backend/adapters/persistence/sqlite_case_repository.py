"""SQLite implementation of CaseRepositoryPort.

This is the adapter side of the port Nisal defined in
core/application/ports/case_repository_port.py. The application layer only
ever sees that port, so it never learns that cases are stored in SQLite - it
could be swapped for PostgreSQL by writing a different class here and
changing nothing else.

Two things this class is responsible for:

  Keeping SQL in here. Nothing outside this file writes a query, so the rest
  of the system has no idea what the table is called or what columns it has.

  Translating between the domain model and a database row. The Case model
  has created_at as a real datetime, but SQLite has no date type at all, so
  it is stored as ISO-8601 text and turned back into a datetime on the way
  out. Callers never see the text form.
"""

from datetime import datetime, timezone

from core.application.ports.case_repository_port import CaseRepositoryPort
from core.domain.models.case import Case


class SqliteCaseRepository(CaseRepositoryPort):
    """Stores cases in the SQLite case database."""

    def __init__(self, connection):
        """Takes an open connection rather than a file path.

        This matters: every repository in a case shares one connection, so
        they can be committed together, and a test can pass a ':memory:'
        connection and get a real database with no file on disk.
        """
        self._connection = connection

    def save(self, case: Case) -> None:
        """Write a case, replacing it if the id is already there.

        Replacing rather than failing means re-running the pipeline on the
        same case does not crash. The case row is only metadata - the name
        and the examiner - so overwriting it does not touch any evidence.
        """
        self._connection.execute(
            """
            INSERT OR REPLACE INTO cases (case_id, case_name, examiner, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                case.case_id,
                case.case_name,
                case.examiner,
                _timestamp_to_text(case.created_at),
            ),
        )
        self._connection.commit()

    def find_by_id(self, case_id: str):
        """Return the case with this id, or None if there is not one.

        None rather than an exception, because "we do not have that case" is
        a normal answer to a lookup, not an error.
        """
        row = self._connection.execute(
            """
            SELECT case_id, case_name, examiner, created_at
            FROM cases
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()

        if row is None:
            return None
        return _row_to_case(row)


def _row_to_case(row) -> Case:
    """Turn one database row back into the domain model."""
    return Case(
        case_id=row["case_id"],
        case_name=row["case_name"],
        examiner=row["examiner"],
        created_at=_text_to_timestamp(row["created_at"]),
    )


def _timestamp_to_text(value: datetime) -> str:
    """datetime -> the text we store, e.g. 2026-09-23T10:15:00Z.

    Always UTC. A datetime with no timezone on it is treated as UTC rather
    than as local time, because guessing a local timezone here would put the
    wrong time in the database with nothing to show it had happened.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text_to_timestamp(text: str) -> datetime:
    """The stored text -> a timezone-aware datetime in UTC."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
