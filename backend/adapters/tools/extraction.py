"""Bridge utility adapter APIs to the application extraction ports.

Construct these at the composition boundary and inject them into extraction use
cases. Evidence verification remains the use cases' responsibility. Tool failures
propagate to the caller; no failed extraction is converted into an empty result.
"""

from collections.abc import Callable

from adapters.tools.ibd2sdi_adapter import Ibd2SdiAdapter
from adapters.tools.ibd2sql_adapter import Ibd2SqlAdapter
from adapters.tools.mysqlbinlog_adapter import MysqlBinlogAdapter
from core.application.models import DecodedBinlog
from core.domain.models.canonical import PhysicalRecord, Schema


class Ibd2SdiSchemaExtractor:
    """Adapt a single extracted Schema to the SchemaExtractor sequence contract."""

    def __init__(self, adapter: Ibd2SdiAdapter) -> None:
        self._adapter = adapter

    def extract(self, working_copy_path: str) -> tuple[Schema, ...]:
        return (self._adapter.extract_schema(working_copy_path),)


class Ibd2SqlPhysicalRowExtractor:
    """Extract live rows, optionally followed by recoverable deleted rows.

    Deleted-row recovery is opt-in and executes a second tool invocation. If that
    invocation fails, the use case receives an error and saves no partial bundle.
    """

    def __init__(self, adapter: Ibd2SqlAdapter, *, include_deleted: bool = False) -> None:
        self._adapter = adapter
        self._include_deleted = include_deleted

    def extract(self, working_copy_path: str) -> tuple[PhysicalRecord, ...]:
        records = tuple(self._adapter.extract_records(working_copy_path))
        if self._include_deleted:
            records += tuple(self._adapter.extract_records(working_copy_path, deleted=True))
        return records


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
    ) -> None:
        self._adapter = adapter
        self._schema_lookup = schema_lookup

    def decode(self, working_copy_path: str) -> DecodedBinlog:
        events, markers, warnings = self._adapter.decode(working_copy_path, self._schema_lookup)
        return DecodedBinlog(tuple(events), tuple(markers), tuple(warnings))
