"""SQLite implementation of the warning repository.

Warnings are stored, not logged, because they have to reach the report. A
column the adapter skipped or an event it could not map changes how far a
conclusion can be trusted, and a warning that only went to stdout is one
nobody will read.

Warnings are only ever added, never replaced. Unlike rows or events there is
nothing that identifies "the same warning" across two runs, and deleting old
ones on a re-run could hide something that happened the first time.
"""

import json
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from adapters.persistence._timestamps import to_text
from adapters.persistence._transactions import transaction
from core.application.ports.warning_repository_port import WarningRepositoryPort
from core.domain.models.canonical import AnalysisWarning

_COLUMNS = """
    warning_id, case_id, evidence_id, tool_run_id, code, message,
    context_json, created_at
"""

# created_at and then rowid, so warnings saved in the same instant still
# come back in the order they were raised.
_ORDER = "ORDER BY created_at, rowid"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteWarningRepository(WarningRepositoryPort):
    """Stores the things an adapter could not handle."""

    def __init__(self, connection, now: Callable[[], datetime] = _utc_now):
        # The clock is passed in so tests can fix the time.
        self._connection = connection
        self._now = now

    def save_many(self, warnings: Sequence[AnalysisWarning], case_id: str,
                  evidence_id: Optional[str] = None,
                  tool_run_id: Optional[str] = None) -> None:
        if not warnings:
            return

        created_at = to_text(self._now())
        start = self._connection.execute(
            "SELECT COUNT(*) FROM warnings WHERE case_id = ?", (case_id,)
        ).fetchone()[0]

        rows = [
            (
                f"{case_id}:warning#{start + i}",
                case_id,
                evidence_id,
                tool_run_id,
                warning.code,
                warning.message,
                json.dumps(dict(warning.context)),
                created_at,
            )
            for i, warning in enumerate(warnings)
        ]

        with transaction(self._connection):
            self._connection.executemany(
                f"INSERT INTO warnings ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def list_by_case(self, case_id: str) -> Sequence[AnalysisWarning]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM warnings WHERE case_id = ? {_ORDER}",
            (case_id,),
        ).fetchall()
        return [_row_to_warning(r) for r in rows]

    def list_by_code(self, case_id: str, code: str) -> Sequence[AnalysisWarning]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM warnings WHERE case_id = ? AND code = ? {_ORDER}",
            (case_id, code),
        ).fetchall()
        return [_row_to_warning(r) for r in rows]


def _row_to_warning(row) -> AnalysisWarning:
    return AnalysisWarning(
        code=row["code"],
        message=row["message"],
        context=json.loads(row["context_json"]) if row["context_json"] else {},
    )
