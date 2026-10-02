"""SQLite record of each case's normalization.

The canonical schemas, rows, events and markers are already stored by the
extraction stages, so normalizing a case does not copy them again - two
copies could drift apart. What normalization adds is a decision: which part
of the stored evidence the analysis covers. This table records that decision
and its result: the scope that was used, and for each kind of evidence how
much was in scope out of how much was stored.

The counts are what let a report say "4 of 6 events were in scope" instead
of leaving a reader to wonder whether anything was left out.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional, Tuple

from adapters.persistence._timestamps import from_text, to_text
from adapters.persistence.sqlite_evidence_scope_repository import (
    scope_from_json,
    scope_to_json,
)
from core.application.models import EvidenceScope


@dataclass(frozen=True)
class NormalizationRecord:
    case_id: str
    scope: EvidenceScope
    counts: Mapping[str, Tuple[int, int]]   # kind -> (in scope, stored)
    normalized_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteNormalizationRepository:
    """Stores the latest normalization of each case."""

    def __init__(self, connection, now=_utc_now):
        self._connection = connection
        self._now = now

    def save(self, case_id: str, scope: EvidenceScope,
             counts: Mapping[str, Tuple[int, int]]) -> None:
        """Replace the case's normalization with a new one.

        Only the latest is kept: an analysis always runs on the most recent
        normalization, and the scope it used is stored with it.
        """
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO normalizations "
                "(case_id, scope_json, counts_json, normalized_at) VALUES (?, ?, ?, ?)",
                (
                    case_id,
                    scope_to_json(scope),
                    json.dumps({kind: list(pair) for kind, pair in counts.items()}),
                    to_text(self._now()),
                ),
            )

    def find(self, case_id: str) -> Optional[NormalizationRecord]:
        row = self._connection.execute(
            "SELECT case_id, scope_json, counts_json, normalized_at "
            "FROM normalizations WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return NormalizationRecord(
            case_id=row["case_id"],
            scope=scope_from_json(row["scope_json"]),
            counts={kind: tuple(pair) for kind, pair in json.loads(row["counts_json"]).items()},
            normalized_at=from_text(row["normalized_at"]),
        )
