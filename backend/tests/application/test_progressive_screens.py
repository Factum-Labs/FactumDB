"""Desktop pages match archival projections without full-case reads."""
import json

import pytest

from tests.application.auth_support import authenticated_runtime as DesktopRuntime
from tests.application.test_desktop_runtime import create, call, response
from tests.fixtures.datasets import DS02
from tests.fixtures.pipeline import run_pipeline


@pytest.fixture
def saved(tmp_path):
    runtime = DesktopRuntime(tmp_path / 'workspace')
    case_id = create(runtime)
    result = run_pipeline(DS02)
    stores = runtime.session(case_id)[1]
    for stage in ('grouping', 'correlation', 'reconstruction', 'reconciliation'):
        getattr(stores.domain, 'save_' + stage)(case_id, getattr(result, stage))
    yield runtime, case_id
    runtime.close()


def test_header_never_reads_analysis_json(saved, monkeypatch):
    runtime, case_id = saved
    c = runtime.session(case_id)[0]
    statements = []
    c.set_trace_callback(statements.append)
    monkeypatch.setattr('sidecar.desktop.case_view', lambda *args: pytest.fail('full projection'))
    header = call(runtime, 'get_case_header', case_id=case_id)
    assert header['pipeline']['metrics']['transactions'] > 0
    assert header['pipeline']['metrics']['exact'] is not None
    assert header['revision']
    assert not any('result_json' in sql.lower() for sql in statements)
    c.set_trace_callback(None)


def test_pages_details_and_counts_match_full_projection(saved):
    runtime, case_id = saved
    full = call(runtime, 'get_case_data', case_id=case_id)
    tx = call(runtime, 'get_screen_page', case_id=case_id, kind='transactions', limit=1)
    assert tx['total'] == len(full['analysis']['grouping']['transactions'])
    assert tx['items'] == full['analysis']['grouping']['transactions'][:1]
    detail = call(runtime, 'get_screen_detail', case_id=case_id, kind='transactions', identity=tx['items'][0]['id'])
    assert 'events' not in detail['detail']
    events = call(runtime, 'get_screen_page', case_id=case_id, kind='events', bucket=tx['items'][0]['id'], limit=1)
    assert len(events['items']) <= 1
    recon = call(runtime, 'get_screen_page', case_id=case_id, kind='reconciliation', limit=1)
    assert recon['total'] == len(full['analysis']['reconciliation']['records'])
    for result in ('Exact', 'Conflicting', 'Unresolved'):
        filtered = call(runtime, 'get_screen_page', case_id=case_id, kind='reconciliation', bucket=result, limit=1)
        assert filtered['total'] == sum(r['rollup'] == result for r in full['analysis']['reconciliation']['records'])
        assert all(r['result'] == result for r in filtered['items'])
    groups = call(runtime, 'get_screen_page', case_id=case_id, kind='finding_groups')
    assert sum(g['occurrences'] for g in groups['items']) == len(full['findings'])
    for group in groups['items']:
        assert group['entries'] == []
        findings = call(runtime, 'get_screen_page', case_id=case_id, kind='findings', bucket=group['id'], limit=1)
        assert findings['total'] == group['occurrences']
        assert len(findings['items']) == 1


def test_rebuild_invalidation_and_legacy_header(saved):
    runtime, case_id = saved
    c = runtime.session(case_id)[0]
    before = call(runtime, 'get_case_header', case_id=case_id)['revision']
    # Simulate an older case with only archival results.
    with c:
        c.execute('DELETE FROM screen_items WHERE case_id=?', (case_id,))
        c.execute('DELETE FROM screen_summary WHERE case_id=?', (case_id,))
    header = call(runtime, 'get_case_header', case_id=case_id)
    assert header['pipeline']['metrics']['transactions'] is None
    page = call(runtime, 'get_screen_page', case_id=case_id, kind='transactions', limit=1)
    assert page['total'] > 0
    with c:
        c.execute("DELETE FROM analysis_results WHERE case_id=? AND stage='grouping'", (case_id,))
    assert call(runtime, 'get_screen_page', case_id=case_id, kind='transactions')['total'] == 0
    assert call(runtime, 'get_case_header', case_id=case_id)['revision'] != before


def test_history_detail_is_selected_and_step_pages_are_complete(saved):
    runtime, case_id = saved
    page = call(runtime, 'get_screen_page', case_id=case_id, kind='histories', limit=1)
    record = page['items'][0]['record']
    detail = call(runtime, 'get_screen_detail', case_id=case_id, kind='histories', identity=record['id'], bucket=record['table'])['detail']
    assert detail['steps_paginated'] is True
    assert len(detail['steps']) <= 101
    steps = call(runtime, 'get_screen_page', case_id=case_id, kind='history_steps', bucket=json.dumps([record['table'], record['id']], separators=(',', ':')), limit=1)
    assert steps['total'] == detail['step_count']
    assert len(steps['items']) <= 1


def test_legacy_rollup_cards_do_not_require_field_totals(saved):
    runtime, case_id = saved
    c = runtime.session(case_id)[0]
    with c:
        c.execute('DELETE FROM screen_items WHERE case_id=?', (case_id,))
        c.execute('DELETE FROM screen_summary WHERE case_id=?', (case_id,))
    page = call(runtime, 'get_screen_page', case_id=case_id, kind='reconciliation', limit=1)
    summary = page['summaries']['reconciliation']
    assert sum(summary['counts'].values()) == page['total']
    assert 'exact' not in summary and 'comparisons' not in summary
    assert call(runtime, 'get_case_header', case_id=case_id)['pipeline']['metrics']['exact'] is None
    complete = call(runtime, 'get_screen_summary', case_id=case_id)['summaries']['reconciliation']
    assert complete['comparisons'] > page['total']
    assert call(runtime, 'get_case_header', case_id=case_id)['pipeline']['metrics']['exact'] == complete['exact']


def test_screen_routes_validate_bounds_and_ownership(saved):
    runtime, case_id = saved
    for bad in (-1, 101, True, '100'):
        assert not response(runtime, 'get_screen_page', case_id=case_id, kind='transactions', limit=bad)['ok']
    assert not response(runtime, 'get_screen_page', case_id=case_id, kind='arbitrary_table')['ok']
    runtime.auth.logout({})
    for command in ('get_case_header', 'get_screen_page', 'get_screen_detail', 'get_screen_context', 'get_screen_coverage', 'get_screen_summary', 'locate_screen_item'):
        assert response(runtime, command, case_id=case_id, kind='transactions')['error_code'] == 'AuthenticationRequiredError'
