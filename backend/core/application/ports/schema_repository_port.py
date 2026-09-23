"""Port for the table schemas extracted by the ibd2sdi adapter."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence, Tuple

from core.domain.models.canonical import Schema


class SchemaRepositoryPort(ABC):
    """Stores table shapes, and serves them back to the domain layer.

    Backs the `schemas` and `schema_columns` tables in docs/sqlite-schema.md
    sections 4 and 5.

    `schema_for` and `tables` are the two methods of the domain layer's
    SchemaCatalog protocol. They are named the same on purpose: an
    implementation of this port can be passed directly wherever a
    SchemaCatalog is expected, so one class both stores schemas and answers
    the correlation services' lookups.

    That lookup is the hottest read in the whole system - every single binlog
    row event needs it to turn @1, @2, @3 into column names - which is why
    schema_columns is a real table keyed on (schema_id, position) rather than
    a JSON blob that would have to be parsed each time.
    """

    @abstractmethod
    def save(self, schema: Schema, evidence_id: str, tool_run_id: str) -> str:
        """Save a schema and its columns, and return the new schema_id.

        The schema itself does not carry evidence_id or tool_run_id - those
        belong to the storage layer, not to the canonical model - so they are
        passed in here.
        """
        raise NotImplementedError

    @abstractmethod
    def schema_for(self, database: str, table: str) -> Optional[Schema]:
        """The schema for one table, or None if we do not have it.

        SchemaCatalog.schema_for. Returning None matters: a binlog can mention
        a table whose .ibd was never seized, and that is a normal evidence gap
        rather than an error.
        """
        raise NotImplementedError

    @abstractmethod
    def tables(self) -> Sequence[Tuple[str, str]]:
        """Every (database, table) a schema is available for.

        SchemaCatalog.tables.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_evidence(self, evidence_id: str) -> Sequence[Schema]:
        """Every schema extracted from one evidence file."""
        raise NotImplementedError
