"""Primary-key lookups retaining every physical candidate, including remnants."""
from collections.abc import Sequence
from core.domain.models.canonical import PhysicalRecord
from core.domain.models.correlation import RecordCorrelation
from core.domain.models.identity import RecordKey, UnrenderableKey, render_key_value
from core.domain.ports import SchemaCatalog, PhysicalRecordSource


class PhysicalIndex:
    def __init__(self, schemas: SchemaCatalog, physical: PhysicalRecordSource) -> None:
        self._schemas, self._physical = schemas, physical
        self._tables: dict[tuple[str, str], dict[RecordKey, list[PhysicalRecord]]] = {}

    def candidates(self, key: RecordKey) -> Sequence[PhysicalRecord]:
        pair = (key.database, key.table)
        if pair not in self._tables:
            by_key: dict[RecordKey, list[PhysicalRecord]] = {}
            schema = self._schemas.schema_for(*pair)
            if schema is not None:
                columns = tuple(c.name for c in schema.primary_key_columns())
                for record in self._physical.records_for(*pair):
                    try:
                        values = tuple(render_key_value(c, record.values[c]) for c in columns)
                    except (UnrenderableKey, KeyError):
                        continue
                    actual = RecordKey(*pair, columns, values)
                    by_key.setdefault(actual, []).append(record)
            self._tables[pair] = by_key
        return self._tables[pair].get(key, ())

    def selected(self, correlation: RecordCorrelation) -> PhysicalRecord | None:
        ref = correlation.physical
        if ref is None:
            return None
        for record in self.candidates(correlation.record.to_key()):
            if (record.is_deleted, record.page_no, record.page_offset) == (
                ref.is_deleted, ref.page_no, ref.page_offset
            ):
                return record
        return None
