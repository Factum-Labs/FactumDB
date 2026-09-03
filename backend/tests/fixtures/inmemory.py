"""In-memory implementations of the domain ports.

These are the whole reason the services can be tested without SQLite, adapters,
or evidence files. They satisfy the Protocols structurally - nothing here
inherits from anything in the domain, which is the same way Gimhan's repositories
will satisfy them.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.domain.models.canonical import (
    BinlogEvent,
    BinlogInventory,
    EventRef,
    IntegrityResult,
    PhysicalRecord,
    ProvenanceReference,
    Schema,
    TransactionMarker,
)
from core.domain.ports import DEFAULT_SUPPORTED_TYPES


class InMemorySchemaCatalog:
    def __init__(self, *schemas: Schema) -> None:
        self._schemas = {(s.database, s.table): s for s in schemas}

    def schema_for(self, database: str, table: str) -> Schema | None:
        return self._schemas.get((database, table))

    def tables(self) -> Sequence[tuple[str, str]]:
        return sorted(self._schemas)


class InMemoryEventSource:
    def __init__(
        self,
        events: Sequence[BinlogEvent] = (),
        markers: Sequence[TransactionMarker] = (),
    ) -> None:
        self._events = list(events)
        self._markers = list(markers)

    def events(self) -> Sequence[BinlogEvent]:
        return list(self._events)

    def markers(self) -> Sequence[TransactionMarker]:
        return list(self._markers)


class InMemoryPhysicalRecordSource:
    def __init__(self, *records: PhysicalRecord) -> None:
        self._records = list(records)

    def records_for(self, database: str, table: str) -> Sequence[PhysicalRecord]:
        return [r for r in self._records if r.database == database and r.table == table]


class InMemoryEvidenceContext:
    """Everything about the evidence set as a whole.

    `inventory=None` means no `mysql-bin.index` was provided, which is a real and
    consequential case - not a shortcut for "assume complete coverage".
    """

    def __init__(
        self,
        *,
        inventory: BinlogInventory | None = None,
        integrity: dict[tuple[str, str], IntegrityResult] | None = None,
        provenance: dict[EventRef, ProvenanceReference] | None = None,
        supported_types: frozenset[str] = DEFAULT_SUPPORTED_TYPES,
        physical_tables: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self._inventory = inventory
        self._integrity = integrity or {}
        self._provenance = provenance or {}
        self._supported_types = supported_types
        self._physical_tables = physical_tables

    def inventory(self) -> BinlogInventory | None:
        return self._inventory

    def integrity_for(self, database: str, table: str) -> IntegrityResult | None:
        return self._integrity.get((database, table))

    def provenance_for(self, ref: EventRef) -> ProvenanceReference | None:
        return self._provenance.get(ref)

    def supported_data_types(self) -> frozenset[str]:
        return self._supported_types

    def tables_with_physical_evidence(self) -> frozenset[tuple[str, str]]:
        return self._physical_tables
