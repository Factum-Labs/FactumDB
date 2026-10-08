"""Regressions for the failures independently reproduced by the MySQL lab."""
from dataclasses import replace
from decimal import Decimal
import pytest

from core.domain.models.canonical import Schema, TableCreation
from core.domain.models.values import UndecodableValue, base_type, compare
from core.domain.ports import DEFAULT_SUPPORTED_TYPES
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.record_reconciliation import ReconciliationService
from core.domain.services.state_reconstruction import StateReconstructionService
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.builders import col, ev, marker, inventory, integrity, phys
from tests.fixtures.inmemory import (InMemorySchemaCatalog, InMemoryEventSource,
    InMemoryPhysicalRecordSource, InMemoryEvidenceContext)

FILE = 'binlog.000018'
TABLE = ('finance', 'notes')
SCHEMA = Schema(*TABLE, (col('id', 1, pk=True), col('note', 2, 'VARCHAR(120)')), 80043)


class CountingRows(InMemoryPhysicalRecordSource):
    def __init__(self, *rows):
        super().__init__(*rows)
        self.calls = 0

    def records_for(self, *args):
        self.calls += 1
        return super().records_for(*args)


def pipeline(events=(), rows=(), *, schema=SCHEMA, inv=True, damaged=False,
             extracted=True, creations=()):
    pair = (schema.database, schema.table)
    context = InMemoryEvidenceContext(
        inventory=inventory(FILE) if inv else None,
        physical_tables=frozenset({pair}),
        extracted_tables=frozenset({pair}) if extracted else frozenset(),
        integrity={pair: integrity('damaged', 1) if damaged else integrity()},
        table_creations=creations,
    )
    schemas, physical = InMemorySchemaCatalog(schema), CountingRows(*rows)
    positions = tuple(dict.fromkeys(e.log_position for e in events))
    markers = [marker('committed', 90, 900, event_positions=positions)] if events else []
    grouping = TransactionGroupingService(context).group(InMemoryEventSource(events, markers))
    correlation = RecordCorrelationService(schemas, physical, context).correlate(grouping)
    history = StateReconstructionService(schemas, physical, context).reconstruct(grouping, correlation)
    result = ReconciliationService(schemas, physical, context).reconcile(history, correlation, grouping.coverage)
    return grouping, correlation, history, result, physical.calls


def insert(id, *, index=0, position=100):
    return replace(ev('INSERT', position, table='notes', after={'id': id, 'note': 'before'}), row_index=index)


def test_multirow_accounting_order_and_real_duplicate():
    events = [insert(2, index=1), insert(1), insert(1)]
    grouping, *_ = pipeline(events)
    assert grouping.event_count == 2
    assert [g.event.after['id'] for g in grouping.transactions[0].events] == [1, 2]
    assert [f.rule_id for f in grouping.findings].count('R-GRP-013') == 1
    assert grouping.transaction_for(events[0].ref) is grouping.transactions[0]
    assert grouping.event_for(events[0].ref) is events[0]


def test_minimal_note_update_keeps_history_and_images_sparse():
    update = ev('UPDATE', 200, table='notes', before={'id': 1}, after={'note': 'after'})
    _, corr, history, result, _ = pipeline([insert(1), update], [phys('notes', {'id': 1, 'note': 'after'})])
    assert 'R-CORR-003' not in {f.rule_id for f in corr.findings}
    assert len(corr.records[0].log_event_refs) == 2
    assert history.histories[0].final_log_state.value('note') == 'after'
    assert update.after == {'note': 'after'}
    assert not any(f.result.value == 'Conflicting' for f in result.rows)


def test_minimal_composite_key_change_merges_only_identity():
    schema = Schema(*TABLE, (col('id', 1, pk=True), col('part', 2, pk=True), col('note', 3, 'text')), 80043)
    first = replace(insert(1), after={'id': 1, 'part': 2, 'note': 'before'})
    update = ev('UPDATE', 200, table='notes', before={'id': 1, 'part': 2}, after={'part': 3})
    _, corr, history, _, _ = pipeline([first, update], [phys('notes', {'id': 1, 'part': 3, 'note': 'before'})], schema=schema)
    assert len(corr.records) == 1
    assert corr.records[0].record.to_key().values == ('1', '3')
    assert history.histories[0].final_log_state.value('note') == 'before'
    assert update.after == {'part': 3}


def test_explicit_unreadable_changed_key_does_not_fall_back():
    update = ev('UPDATE', 200, table='notes', before={'id': 1}, after={'id': UndecodableValue('bad bytes')})
    _, corr, *_ = pipeline([insert(1), update])
    assert next(c for c in corr.event_correlations if c.ref == update.ref).record_id is None
    assert 'R-CORR-003' in {f.rule_id for f in corr.findings}


@pytest.mark.parametrize('declaration,value', [('VARCHAR(120)', 'hello'), ('decimal(12,2) unsigned', Decimal('4.20')), (' INT UNSIGNED', 4)])
def test_parameterized_supported_types(declaration, value):
    assert compare(value, value, col('v', 1, declaration), DEFAULT_SUPPORTED_TYPES).equal
    assert base_type(declaration) in DEFAULT_SUPPORTED_TYPES


@pytest.mark.parametrize('declaration', ['JSON', 'BLOB', 'DOUBLE', 'FLOAT'])
def test_unvalidated_types_stay_unsupported(declaration):
    assert not compare('x', 'x', col('v', 1, declaration), DEFAULT_SUPPORTED_TYPES).comparable


@pytest.mark.parametrize('inv,damaged,extracted,expected', [(True, False, True, 'Conflicting'), (False, False, True, 'Unresolved'), (True, True, True, 'Unresolved'), (True, False, False, 'Unresolved')])
def test_hidden_deletion_requires_healthy_complete_evidence(inv, damaged, extracted, expected):
    *_, result, _ = pipeline([insert(1)], inv=inv, damaged=damaged, extracted=extracted)
    presence = next(f for f in result.rows if f.field == 'record presence')
    assert presence.result.value == expected


def test_logged_deletion_has_known_absence_without_fabricating_column_values():
    deletion = ev('DELETE', 200, table='notes', before={'id': 1}, after=None)
    *_, result, _ = pipeline([insert(1), deletion])
    presence = next(f for f in result.rows if f.field == 'record presence')
    assert presence.result.value == 'Exact' and presence.phys_display == 'absent'
    assert all(f.phys_display == 'not observed' for f in result.rows if f.field != 'record presence')


@pytest.mark.parametrize('creation,inv,expected', [(False, True, 'Unresolved'), (True, False, 'Unresolved'), (True, True, 'Conflicting')])
def test_physical_only_row_needs_creation_proof(creation, inv, expected):
    creations = (TableCreation(*TABLE, FILE, 50),) if creation else ()
    *_, result, _ = pipeline(rows=[phys('notes', {'id': 99, 'note': 'hidden'})], inv=inv, creations=creations)
    assert result.rows[0].result.value == expected


def test_indexes_bound_table_reads_and_preserve_ambiguity():
    events = [insert(i, index=i) for i in range(100)]
    rows = [phys('notes', {'id': i, 'note': 'before'}) for i in range(100)]
    rows.append(phys('notes', {'id': 7, 'note': 'second'}, page_offset=190))
    _, corr, _, result, reads = pipeline(events, rows)
    assert reads <= 5
    assert corr.record('notes:7').method.is_ambiguous
    assert len(corr.record('notes:7').physical_candidates) == 2
    assert result.record('notes:7').fields[0].result.value == 'Unresolved'


def test_physical_only_ambiguity_is_not_hidden_by_the_index():
    rows = [phys('notes', {'id': 99, 'note': 'one'}), phys('notes', {'id': 99, 'note': 'two'}, page_offset=190)]
    _, corr, _, result, _ = pipeline(rows=rows, creations=(TableCreation(*TABLE, FILE, 50),))
    assert len(corr.records[0].physical_candidates) == 2
    assert corr.records[0].method.is_ambiguous
    assert result.rows[0].result.value == 'Unresolved'


def test_incomplete_tail_limits_rows_last_seen_in_an_earlier_file():
    context = InMemoryEvidenceContext(inventory=inventory(FILE, 'binlog.000019'),
        physical_tables=frozenset({TABLE}), extracted_tables=frozenset({TABLE}), integrity={TABLE: integrity()})
    events = [insert(1), replace(insert(2), source_file='binlog.000019')]
    markers = [marker('committed', 90, 150, event_positions=(100,)),
               marker('incomplete', 90, 150, source_file='binlog.000019', event_positions=(100,))]
    schemas = InMemorySchemaCatalog(SCHEMA)
    physical = InMemoryPhysicalRecordSource(phys('notes', {'id': 1, 'note': 'could be in missing tail'}))
    grouping = TransactionGroupingService(context).group(InMemoryEventSource(events, markers))
    corr = RecordCorrelationService(schemas, physical, context).correlate(grouping)
    history = StateReconstructionService(schemas, physical, context).reconstruct(grouping, corr)
    result = ReconciliationService(schemas, physical, context).reconcile(history, corr, grouping.coverage)
    assert history.history('notes:1').gap_touched
    assert next(f for f in result.record('notes:1').fields if f.field == 'note').result.value == 'Unresolved'
    assert history.history('notes:2').final_log_state.presence.value == 'absent'


def test_unidentified_key_prevents_absence_claim_for_physical_only_row():
    unidentified = ev('INSERT', 100, table='notes', after={'id': UndecodableValue('unreadable key'), 'note': 'hidden'})
    *_, result, _ = pipeline([unidentified], [phys('notes', {'id': 99, 'note': 'hidden'})],
                            creations=(TableCreation(*TABLE, FILE, 50),))
    assert result.rows[0].result.value == 'Unresolved'
