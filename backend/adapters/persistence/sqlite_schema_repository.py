"""SQLite implementation of the schema repository.

Two things make this one different from the repositories before it.

It writes two tables. A schema row in `schemas` and one row per column in
`schema_columns`. Those have to land together: a schema with no columns is
worse than no schema at all, because a lookup would find it and then map
every @N to nothing. Both writes happen inside one transaction so either
both are there or neither is.

It serves the hottest read in the system. schema_for() is what turns
mysqlbinlog's @1, @2, @3 into column names, and it runs for every single row
event. That is why schema_columns is a real table keyed on
(schema_id, position) rather than a JSON blob that would have to be parsed
on each lookup.

schema_for() and tables() are also the two methods of the domain layer's
SchemaCatalog protocol, so this class can be handed straight to the
correlation services with nothing in between.
"""

from typing import Optional, Sequence, Tuple

from core.application.ports.schema_repository_port import SchemaRepositoryPort
from core.domain.models.canonical import Column, Schema


class SqliteSchemaRepository(SchemaRepositoryPort):
    """Stores table schemas and answers the domain layer's lookups."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, schema: Schema, evidence_id: str, tool_run_id: str) -> str:
        """Write a schema and its columns, and return the schema_id.

        The id is derived from what already identifies a schema uniquely -
        the evidence file plus the table it describes, which is exactly what
        the UNIQUE constraint on `schemas` says. Deriving it rather than
        generating a random one means re-running the extraction on the same
        evidence produces the same ids, so two runs of the pipeline give
        identical databases. Repeatability is one of the project's evaluation
        metrics, not just a convenience.

        It also reads plainly in a query result, which a UUID does not.
        """
        schema_id = _schema_id(evidence_id, schema.database, schema.table)

        # One transaction: the schema row and its columns land together, or
        # neither does. A schema with no columns would be found by a lookup
        # and then map every @N to nothing.
        with self._connection:
            # Delete first so a re-extraction that found fewer columns does
            # not leave the old extras behind.
            self._connection.execute(
                "DELETE FROM schema_columns WHERE schema_id = ?", (schema_id,)
            )
            self._connection.execute(
                """
                INSERT OR REPLACE INTO schemas
                    (schema_id, evidence_id, tool_run_id, database_name,
                     table_name, mysql_version_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    schema_id,
                    evidence_id,
                    tool_run_id,
                    schema.database,
                    schema.table,
                    schema.mysql_version_id,
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO schema_columns
                    (schema_id, position, name, data_type, is_nullable, is_primary_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        schema_id,
                        column.position,
                        column.name,
                        column.data_type,
                        int(column.is_nullable),
                        int(column.is_primary_key),
                    )
                    for column in schema.columns
                ],
            )

        return schema_id

    def schema_for(self, database: str, table: str) -> Optional[Schema]:
        """The schema for one table, or None if we do not have it.

        Returning None matters. A binlog can name a table whose .ibd was never
        seized, and that is an ordinary evidence gap rather than an error.

        If the same table was extracted from more than one evidence file, the
        most recently stored one wins. That is the right choice for a lookup
        used during correlation: the newest extraction is the one matching the
        evidence currently being analysed.
        """
        row = self._connection.execute(
            """
            SELECT schema_id, database_name, table_name, mysql_version_id
            FROM schemas
            WHERE database_name = ? AND table_name = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (database, table),
        ).fetchone()

        return self._load(row) if row is not None else None

    def tables(self) -> Sequence[Tuple[str, str]]:
        """Every (database, table) a schema is available for.

        Sorted so the list is the same on every run.
        """
        rows = self._connection.execute(
            """
            SELECT DISTINCT database_name, table_name
            FROM schemas
            ORDER BY database_name, table_name
            """
        ).fetchall()
        return [(r["database_name"], r["table_name"]) for r in rows]

    def list_by_evidence(self, evidence_id: str) -> Sequence[Schema]:
        rows = self._connection.execute(
            """
            SELECT schema_id, database_name, table_name, mysql_version_id
            FROM schemas
            WHERE evidence_id = ?
            ORDER BY database_name, table_name
            """,
            (evidence_id,),
        ).fetchall()
        return [self._load(r) for r in rows]

    def _load(self, row) -> Schema:
        """Rebuild a Schema and its columns from a `schemas` row."""
        column_rows = self._connection.execute(
            """
            SELECT position, name, data_type, is_nullable, is_primary_key
            FROM schema_columns
            WHERE schema_id = ?
            ORDER BY position
            """,
            (row["schema_id"],),
        ).fetchall()

        columns = tuple(
            Column(
                name=c["name"],
                position=c["position"],
                data_type=c["data_type"],
                is_nullable=bool(c["is_nullable"]),
                is_primary_key=bool(c["is_primary_key"]),
            )
            for c in column_rows
        )

        return Schema(
            database=row["database_name"],
            table=row["table_name"],
            columns=columns,
            mysql_version_id=row["mysql_version_id"],
        )


def _schema_id(evidence_id: str, database: str, table: str) -> str:
    """The natural key, written as one string.

    Matches the UNIQUE constraint on `schemas`, and follows the same readable
    style as the domain layer's record references.
    """
    return f"{evidence_id}:{database}.{table}"
