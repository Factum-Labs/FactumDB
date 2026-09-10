"""Ports: the only way the domain reaches anything outside itself.

All reads, all Protocols. A service takes these in its constructor and nothing
else, so the domain never learns whether the evidence came from SQLite, a JSON
fixture, or an adapter running live - which is what makes the same services
usable in a test and in the real pipeline.

Structural typing (Protocol rather than ABC) is deliberate: Gimhan's repositories
satisfy these by having the right methods, without importing anything from the
domain or inheriting from it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

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

#: The data types the pipeline has actually been validated against. Anything
#: outside this set reconciles to Unsupported rather than being compared on the
#: assumption that our decoding is right.
DEFAULT_SUPPORTED_TYPES: frozenset[str] = frozenset(
    {
        "tinyint",
        "smallint",
        "mediumint",
        "int",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "char",
        "varchar",
        "text",
        "tinytext",
        "mediumtext",
        "longtext",
        "date",
        "datetime",
        "timestamp",
        "enum",
    }
)


class SchemaCatalog(Protocol):
    """Table shapes, from the `ibd2sdi` adapter."""

    def schema_for(self, database: str, table: str) -> Schema | None: ...

    def tables(self) -> Sequence[tuple[str, str]]:
        """Every `(database, table)` a schema is available for."""
        ...


class EventSource(Protocol):
    """Decoded binlog events and the transaction markers around them."""

    def events(self) -> Sequence[BinlogEvent]: ...

    def markers(self) -> Sequence[TransactionMarker]: ...


class PhysicalRecordSource(Protocol):
    """Rows read out of the `.ibd` files, including deleted remnants."""

    def records_for(self, database: str, table: str) -> Sequence[PhysicalRecord]: ...


class EvidenceContext(Protocol):
    """Everything about the evidence set as a whole.

    This is what lets the services distinguish "the evidence disagrees" from "the
    evidence is incomplete" - the single most important distinction the tool
    makes.
    """

    def inventory(self) -> BinlogInventory | None:
        """The server's own binlog list, or None if `mysql-bin.index` is absent.

        None is never read as "we have every log". Absence of the index means we
        cannot tell, which keeps coverage incomplete.
        """
        ...

    def integrity_for(self, database: str, table: str) -> IntegrityResult | None:
        """`innochecksum` result for the tablespace backing this table."""
        ...

    def provenance_for(self, ref: EventRef) -> ProvenanceReference | None:
        """Tool-run provenance for one event, when the adapter recorded it."""
        ...

    def supported_data_types(self) -> frozenset[str]:
        """Lowercase type names the pipeline has been validated against."""
        ...

    def tables_with_physical_evidence(self) -> frozenset[tuple[str, str]]:
        """Tables an `.ibd` was actually registered for.

        A table with binlog events but no tablespace in the evidence set has an
        unobserved physical side, which reconciles to Unresolved. Without this,
        "we were not given the file" would look identical to "the row is not
        there" - and the second one is a far stronger claim.
        """
        ...
