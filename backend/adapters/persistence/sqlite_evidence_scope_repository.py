"""SQLite storage for the scope an investigator chose for a case.

A case has at most one scope. Saving a new one replaces the old one, because
the scope is a setting rather than evidence - what each analysis actually
used is kept separately, in the normalizations table.
"""

import json
from datetime import datetime, timezone

from adapters.persistence._timestamps import to_text
from core.application.models import EvidenceScope


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteEvidenceScopeRepository:
    """Stores which databases and tables each case covers."""

    def __init__(self, connection, now=_utc_now):
        self._connection = connection
        self._now = now

    def save(self, case_id: str, scope: EvidenceScope) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO case_scopes (case_id, scope_json, updated_at) "
                "VALUES (?, ?, ?)",
                (case_id, scope_to_json(scope), to_text(self._now())),
            )

    def scope_for(self, case_id: str) -> EvidenceScope:
        """The case's scope, or everything if none was ever set."""
        row = self._connection.execute(
            "SELECT scope_json FROM case_scopes WHERE case_id = ?", (case_id,)
        ).fetchone()
        return scope_from_json(row["scope_json"]) if row is not None else EvidenceScope()


def scope_to_json(scope: EvidenceScope) -> str:
    """Sorted, so the same scope is always stored as the same text."""
    return json.dumps({
        "databases": sorted(scope.databases),
        "tables": [list(pair) for pair in sorted(scope.tables)],
    })


def scope_from_json(text: str) -> EvidenceScope:
    data = json.loads(text)
    return EvidenceScope(
        databases=frozenset(data["databases"]),
        tables=frozenset(tuple(pair) for pair in data["tables"]),
    )
