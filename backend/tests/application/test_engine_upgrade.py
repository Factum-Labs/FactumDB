"""An engine upgrade keeps evidence and audit history but retires old verdicts."""
import json
from tests.application.auth_support import authenticated_runtime as DesktopRuntime
from tests.application.test_desktop_runtime import create, evidence, tools, finish, call


def test_upgrade_invalidation_restart_redecode_and_exports(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    runtime = DesktopRuntime(root)
    case_id = create(runtime)
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)['complete']
    before = call(runtime, 'get_case_data', case_id=case_id)
    conn, _, _ = runtime.session(case_id)
    conn.execute('UPDATE cases SET engine_revision = 1 WHERE case_id = ?', (case_id,))
    conn.commit()
    runtime.close()

    runtime = DesktopRuntime(root)
    try:
        stale = call(runtime, 'get_case_data', case_id=case_id)
        assert stale['analysis'] == {} and stale['run'] is None
        assert stale['case']['engine_revision'] == 2 and stale['case']['reanalysis_required']
        assert call(runtime, 'list_cases')[0]['status'] == 'Needs reanalysis'
        for table in ('evidence_files', 'tool_runs', 'schemas', 'physical_records', 'binlog_events', 'integrity_results'):
            assert stale['tables'][table] == before['tables'][table]
        assert stale['tables']['pipeline_runs'][0]['obsolete'] == 1
        assert stale['tables']['normalizations'] == []
        assert finish(runtime, case_id)['complete']
        current = call(runtime, 'get_case_data', case_id=case_id)
        assert not current['case']['reanalysis_required']
        assert len(current['tables']['tool_runs']) > len(before['tables']['tool_runs'])
        # A fresh mysqlbinlog run, not old normalized results, fed this analysis.
        old_runs = {r['tool_run_id'] for r in before['tables']['tool_runs']}
        assert all(e['tool_run_id'] not in old_runs for e in current['tables']['binlog_events'])
        destination = tmp_path / 'upgraded.json'
        call(runtime, 'export_case', case_id=case_id, format='JSON', path=str(destination))
        exported = json.loads(destination.read_text(encoding='utf-8'))
        assert exported['format_version'] == exported['analysis_format_version'] == exported['engine_revision'] == 2
        assert all('row_index' in e for e in exported['tables']['binlog_events'])
        folder = tmp_path / 'upgraded_csv'
        call(runtime, 'export_case', case_id=case_id, format='CSV', path=str(folder))
        assert 'engine revision: 2' in (folder / 'about.txt').read_text(encoding='utf-8')
    finally:
        runtime.close()
