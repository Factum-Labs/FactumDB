"""Construct the application-facing SQLite integration without owning schema."""

from dataclasses import dataclass

from adapters.persistence.sqlite_binlog_event_repository import SqliteBinlogEventRepository
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_evidence_repository import SqliteEvidenceRepository
from adapters.persistence.sqlite_extraction_repository import (
    SqliteExtractionRepository, TransactionalConnection,
)
from adapters.persistence.sqlite_integrity_repository import SqliteIntegrityRepository
from adapters.persistence.sqlite_physical_record_repository import SqlitePhysicalRecordRepository
from adapters.persistence.sqlite_schema_repository import SqliteSchemaRepository
from adapters.persistence.sqlite_tool_run_repository import SqliteToolRunRepository
from adapters.persistence.sqlite_transaction_repository import SqliteTransactionRepository
from adapters.persistence.sqlite_warning_repository import SqliteWarningRepository


@dataclass(frozen=True, slots=True)
class SqliteApplicationStores:
    cases: SqliteCaseRepository
    evidence: SqliteEvidenceRepository
    tool_runs: SqliteToolRunRepository
    schemas: SqliteSchemaRepository
    extraction: SqliteExtractionRepository

    def schemas_for_case(self, case_id: str) -> SqliteSchemaRepository:
        """Return this case database's catalog after rejecting cross-case use."""
        if self.cases.get(case_id) is None:
            raise LookupError(f"case not found in this database: {case_id}")
        return self.schemas


def build_sqlite_application_stores(connection, *, now=None) -> SqliteApplicationStores:
    shared = TransactionalConnection(connection)
    cases = SqliteCaseRepository(shared)
    evidence = SqliteEvidenceRepository(shared)
    tool_runs = SqliteToolRunRepository(shared)
    schemas = SqliteSchemaRepository(shared)
    integrity = SqliteIntegrityRepository(shared)
    physical = SqlitePhysicalRecordRepository(shared)
    events = SqliteBinlogEventRepository(shared)
    transactions = SqliteTransactionRepository(shared)
    warnings = SqliteWarningRepository(shared, **({"now": now} if now else {}))
    extraction = SqliteExtractionRepository(
        shared, integrity=integrity, schemas=schemas, physical=physical,
        events=events, transactions=transactions, warnings=warnings,
    )
    return SqliteApplicationStores(cases, evidence, tool_runs, schemas, extraction)
