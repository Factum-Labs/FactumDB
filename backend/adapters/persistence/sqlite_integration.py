"""Construct the application-facing SQLite integration without owning schema."""

from dataclasses import dataclass

from adapters.persistence.sqlite_binlog_event_repository import SqliteBinlogEventRepository
from adapters.persistence.sqlite_binlog_inventory_repository import SqliteBinlogInventoryRepository
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_domain_repository import SqliteDomainRepository
from adapters.persistence.sqlite_evidence_normalizer import SqliteEvidenceNormalizer
from adapters.persistence.sqlite_evidence_repository import SqliteEvidenceRepository
from adapters.persistence.sqlite_evidence_scope_repository import SqliteEvidenceScopeRepository
from adapters.persistence.sqlite_extraction_repository import (
    SqliteExtractionRepository, TransactionalConnection,
)
from adapters.persistence.sqlite_integrity_repository import SqliteIntegrityRepository
from adapters.persistence.sqlite_normalization_repository import SqliteNormalizationRepository
from adapters.persistence.sqlite_physical_record_repository import SqlitePhysicalRecordRepository
from adapters.persistence.sqlite_report_repository import SqliteReportRepository
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
    scopes: SqliteEvidenceScopeRepository
    normalizer: SqliteEvidenceNormalizer
    domain: SqliteDomainRepository
    reports: SqliteReportRepository

    def schemas_for_case(self, case_id: str) -> "CaseSchemaCatalog":
        """The schema catalog of one case, for naming that case's @N columns.

        Restricted to the case's own evidence, so another case in the same
        database cannot supply a table's columns.
        """
        if self.cases.get(case_id) is None:
            raise LookupError(f"case not found in this database: {case_id}")
        return CaseSchemaCatalog(self.schemas, case_id)


class CaseSchemaCatalog:
    """The domain's SchemaCatalog, seen from one case."""

    def __init__(self, schemas: SqliteSchemaRepository, case_id: str):
        self._schemas = schemas
        self._case_id = case_id

    def schema_for(self, database, table):
        return self._schemas.schema_for(database, table, case_id=self._case_id)

    def tables(self):
        return self._schemas.tables(case_id=self._case_id)


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
    clock = {"now": now} if now else {}
    warnings = SqliteWarningRepository(shared, **clock)
    scopes = SqliteEvidenceScopeRepository(shared, **clock)
    normalizations = SqliteNormalizationRepository(shared, **clock)
    inventory = SqliteBinlogInventoryRepository(shared)
    extraction = SqliteExtractionRepository(
        shared, integrity=integrity, schemas=schemas, physical=physical,
        events=events, transactions=transactions, warnings=warnings,
        scopes=scopes, normalizations=normalizations, inventory=inventory,
    )
    normalizer = SqliteEvidenceNormalizer(
        cases=cases, scopes=scopes, schemas=schemas, physical=physical,
        events=events, transactions=transactions,
    )
    domain = SqliteDomainRepository(
        shared, cases=cases, normalizations=normalizations, schemas=schemas,
        physical=physical, events=events, transactions=transactions,
        integrity=integrity, inventory=inventory, tool_runs=tool_runs, **clock,
    )
    return SqliteApplicationStores(
        cases, evidence, tool_runs, schemas, extraction, scopes, normalizer, domain,
        SqliteReportRepository(shared, **clock),
    )
