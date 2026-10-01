"""Bridge utility adapter APIs to the application extraction ports.

Construct these at the composition boundary and inject them into extraction use
cases. Evidence verification remains the use cases' responsibility. Tool failures
propagate to the caller; no failed extraction is converted into an empty result.
"""

from collections.abc import Callable

from adapters.tools.ibd2sdi_adapter import Ibd2SdiAdapter
from adapters.tools.ibd2sql_adapter import Ibd2SqlAdapter
from adapters.tools.mysqlbinlog_adapter import MysqlBinlogAdapter
from adapters.tools.audit import AuditedSubprocessRunner
from core.application.models import DecodedBinlog, ProvenancedBatch, ProvenancedResult
from core.application.use_cases.audit import ToolRunAuditService
from core.domain.models.canonical import IntegrityResult
from core.domain.models.canonical import PhysicalRecord, Schema


class Ibd2SdiSchemaExtractor:
    """Adapt a single extracted Schema to the SchemaExtractor sequence contract."""

    def __init__(self, adapter: Ibd2SdiAdapter, audit: ToolRunAuditService | None = None) -> None:
        self._adapter = adapter
        self._audit = audit

    def extract(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[tuple[Schema, ...]]:
        runner = _runner(self._audit, case_id, evidence_id)
        value = (self._adapter.extract_schema(working_copy_path, run=runner.run if runner else None),)
        return _result(value, runner)


class AuditedPageValidator:
    def __init__(self, adapter, audit: ToolRunAuditService | None = None) -> None:
        self._adapter = adapter
        self._audit = audit

    def validate(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[IntegrityResult]:
        runner = _runner(self._audit, case_id, evidence_id)
        value = self._adapter.validate(working_copy_path, run=runner.run if runner else None)
        return _result(value, runner)


class Ibd2SqlPhysicalRowExtractor:
    """Extract live rows, optionally followed by recoverable deleted rows.

    Deleted-row recovery is opt-in and executes a second tool invocation. If that
    invocation fails, the use case receives an error and saves no partial bundle.
    """

    def __init__(self, adapter: Ibd2SqlAdapter, *, include_deleted: bool = False,
                 audit: ToolRunAuditService | None = None) -> None:
        self._adapter = adapter
        self._include_deleted = include_deleted
        self._audit = audit

    def extract(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[tuple[PhysicalRecord, ...]]:
        runner = _runner(self._audit, case_id, evidence_id)
        execute = runner.run if runner else None
        live = tuple(self._adapter.extract_records(working_copy_path, run=execute))
        live_run_id = runner.run_ids[-1] if runner else "unaudited"
        batches = [ProvenancedBatch(live, live_run_id)]
        records = live
        if self._include_deleted:
            deleted = tuple(self._adapter.extract_records(working_copy_path, deleted=True, run=execute))
            deleted_run_id = runner.run_ids[-1] if runner else "unaudited"
            batches.append(ProvenancedBatch(deleted, deleted_run_id))
            records += deleted
        result = _result(records, runner)
        return ProvenancedResult(
            result.value, result.primary_tool_run_id,
            result.contributing_tool_run_ids, tuple(batches),
        )


class MysqlBinlogDecoder:
    """Bind a case-scoped schema lookup and retain every parser warning.

    The lookup must belong to the case being processed (for example a case-bound
    SchemaRepositoryPort.schema_for). Construct one decoder per case; never share
    a lookup across unrelated cases. The application port accepts only a path and
    cannot select the case itself.
    """

    def __init__(
        self,
        adapter: MysqlBinlogAdapter,
        schema_lookup: Callable[[str, str], Schema | None],
        audit: ToolRunAuditService | None = None,
    ) -> None:
        self._adapter = adapter
        self._schema_lookup = schema_lookup
        self._audit = audit

    def decode(self, case_id: str, evidence_id: str, working_copy_path: str) -> ProvenancedResult[DecodedBinlog]:
        runner = _runner(self._audit, case_id, evidence_id)
        events, markers, warnings = self._adapter.decode(
            working_copy_path, self._schema_lookup, run=runner.run if runner else None,
        )
        return _result(DecodedBinlog(tuple(events), tuple(markers), tuple(warnings)), runner)


def _runner(audit, case_id, evidence_id):
    return AuditedSubprocessRunner(audit, case_id, evidence_id) if audit is not None else None


def _result(value, runner):
    run_ids = tuple(runner.run_ids) if runner is not None else ("unaudited",)
    return ProvenancedResult(value, run_ids[-1], run_ids)
