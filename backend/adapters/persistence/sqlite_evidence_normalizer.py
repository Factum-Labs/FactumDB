"""SQLite implementation of the application's EvidenceNormalizer.

The adapters already turn each tool's output into the canonical model: named
columns instead of @1 and @2, UTC timestamps, one event per changed row. What
is left for normalization works on the whole case: gathering everything stored
for it and applying the investigator's scope.

The scope is applied to every kind of evidence in the same way. Filtering a
table's rows but not its binlog events would show the domain services events
for a table with no tablespace, and they would report "we were not given the
file" about a file we do have.

Transactions are where filtering needs care, because one transaction can
change tables inside and outside the scope:

- the positions of out-of-scope events are left out of the marker, so it never
  claims an event the analysis was not given;
- a transaction whose events are all out of scope is left out with them;
- a transaction that listed no events at all is kept, because nothing in it
  says which tables it was about.
"""

from dataclasses import replace

from core.application.errors import NotFoundError
from core.application.models import EvidenceScope, NormalizedEvidence


class SqliteEvidenceNormalizer:
    """Builds a case's normalized evidence from what the case database holds."""

    def __init__(self, *, cases, scopes, schemas, physical, events, transactions):
        self._cases = cases
        self._scopes = scopes
        self._schemas = schemas
        self._physical = physical
        self._events = events
        self._transactions = transactions

    def normalize(self, case_id: str) -> NormalizedEvidence:
        if self._cases.get(case_id) is None:
            raise NotFoundError(f"case not found: {case_id}")
        return scoped_evidence(
            self._scopes.scope_for(case_id),
            schemas=self._schemas,
            physical=self._physical,
            events=self._events,
            transactions=self._transactions,
        )


def scoped_evidence(scope: EvidenceScope, *, schemas, physical, events,
                    transactions) -> NormalizedEvidence:
    """The stored evidence of this case database, narrowed to one scope."""
    in_scope = scope.includes

    kept_schemas = tuple(
        schemas.schema_for(database, table)
        for database, table in schemas.tables()
        if in_scope(database, table)
    )
    kept_records = tuple(
        record
        for database, table in sorted(physical.tables_with_physical_evidence())
        if in_scope(database, table)
        for record in physical.records_for(database, table)
    )
    kept_events = tuple(e for e in events.events() if in_scope(e.database, e.table))

    kept_refs = {(e.source_file, e.log_position) for e in kept_events}
    narrowed = (_narrow(marker, kept_refs) for marker in transactions.markers())
    kept_markers = tuple(marker for marker in narrowed if marker is not None)

    return NormalizedEvidence(kept_schemas, kept_records, kept_events, kept_markers)


def _narrow(marker, kept_refs):
    """The marker listing only in-scope events, or None if none were left."""
    if not marker.event_positions:
        return marker
    positions = tuple(
        position for position in marker.event_positions
        if (marker.source_file, position) in kept_refs
    )
    if not positions:
        return None
    if positions == marker.event_positions:
        return marker
    return replace(marker, event_positions=positions)
