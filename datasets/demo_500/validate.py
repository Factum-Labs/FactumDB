"""Validate demo evidence with the desktop backend and write observed results.

Run from the repository root. Keeps its own case under .validation-cases.
"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / 'backend'))
sys.path.insert(0, str(ROOT.parent / 'attack_lab'))
from verify_app import call, pipeline_seconds
from sidecar.protocol import _json_default
from core.engine import ENGINE_REVISION
from core.domain.rules import RULES
from tests.application.auth_support import authenticated_runtime
from adapters.persistence.case_export import case_export
from sidecar.views import _findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mysql-bin', type=Path, required=True)
    parser.add_argument('--ibd2sql', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'evidence_set')
    args = parser.parse_args()
    source = args.evidence.resolve()
    manifest = json.loads((source / 'manifest.json').read_text())
    for file in manifest['files']:
        path = source / file['path']
        assert path.stat().st_size == file['bytes'], path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == file['sha256'], path
    runtime = authenticated_runtime(ROOT / '.validation-cases')
    try:
        runtime.settings.update({name + '_path': str(args.mysql_bin.resolve() / (name + '.exe'))
                                 for name in ('innochecksum', 'ibd2sdi', 'mysqlbinlog')})
        runtime.settings.update(ibd2sql_path=str(args.ibd2sql.resolve()), python_path=sys.executable, include_deleted=False)
        start = time.monotonic()
        case_id = call(runtime, 'create_case', case_name='Evaluation demo - 500 starting rows', examiner='Demo validation')['case_id']
        for folder in ('ibd', 'binlog'):
            for path in sorted((source / folder).iterdir()):
                call(runtime, 'register_evidence', case_id=case_id, source_path=str(path))
        run = call(runtime, 'start_pipeline', case_id=case_id)
        while not run['stopped']:
            run = call(runtime, 'run_next_stage', run_id=run['run_id'])
            stage = next((s for s in reversed(run['stages']) if s['status'] != 'pending'), {})
            print(f"{stage.get('stage')}: {stage.get('status')}", flush=True)
        view = call(runtime, 'get_case_data', case_id=case_id)
        # The GUI view deliberately defers large arrays. For this small fixture,
        # validate the complete saved archival representation instead.
        connection, _, _ = runtime.session(case_id)
        archive = case_export(connection, case_id)
        view['tables'] = archive['tables']
        view['analysis'] = {row['stage']: row['result'] for row in archive['tables']['analysis_results']}
        found = {}
        _findings(view['analysis'], found)
        view['findings'] = list(found.values())
        elapsed = round(time.monotonic() - start, 3)
        assert run['complete'], run
        analysis = view['analysis']
        recon = analysis['reconciliation']
        records = {r['record']['id']: r for r in recon['records']}
        histories = {h['record']['id']: h for h in analysis['reconstruction']['histories']}
        def field(key, name, result):
            return any(f['field'] == name and f['result'] == result for f in records[key]['fields'])
        rule_counts = Counter(f['rule_id'] for f in view['findings'])
        checks = {
            'all_acquisition_hashes_match': True,
            '500_baseline_rows': sum(manifest['baseline_rows'].values()) == 500,
            '499_live_rows_extracted': len(view['tables']['physical_records']) == 499,
            'hidden_amount_conflicting': field('orders:20', 'amount_minor', 'Conflicting'),
            'hidden_destination_conflicting': field('orders:20', 'destination', 'Conflicting'),
            'hidden_status_conflicting': field('orders:20', 'status', 'Conflicting'),
            'hidden_email_conflicting': field('customers:31', 'email', 'Conflicting'),
            'hidden_role_conflicting': field('staff:8', 'role', 'Conflicting'),
            'hidden_deletion_conflicting': field('payments:25', 'record presence', 'Conflicting'),
            'unlogged_insert_conflicting': field('orders:900001', 'record presence', 'Conflicting'),
            'logged_changes_agree': records['orders:10']['rollup'] == records['staff:7']['rollup'] == 'Exact',
            'logged_deletion_presence_agrees': field('payments:30', 'record presence', 'Exact') and histories['payments:30']['final_log_state']['presence'] == 'absent' and not any(f['result'] == 'Conflicting' for f in records['payments:30']['fields']),
            'before_image_discontinuity_visible': histories['orders:71']['before_image_mismatch'],
            'composite_key_change_visible': 'R-CORR-010' in rule_counts,
            'key_reuse_visible': any(f['rule_id'] == 'R-CORR-012' and f.get('subject', {}).get('id') == 'orders:50' for f in view['findings']),
            'minimal_change_retained_without_conflict': len(histories['orders:60']['steps']) >= 2 and not any(f['result'] == 'Conflicting' for f in records['orders:60']['fields']),
            'rollback_not_invented': histories['orders:40']['final_log_state']['values']['amount_minor'] == 14000 and not any(t['status'] == 'rolled_back' for t in analysis['grouping']['transactions']),
        }
        retained = sum(len(t['events']) for t in analysis['grouping']['transactions']) + len(analysis['grouping']['ungrouped_events'])
        checks['all_decoded_row_events_retained'] = retained == len(view['tables']['binlog_events'])
        checks['no_missing_log_files'] = not analysis['grouping']['coverage']['gaps']
        checks['no_adapter_warnings'] = not view['tables']['warnings']
        selected = ['orders:10', 'orders:20', 'customers:31', 'staff:7', 'staff:8', 'payments:25', 'payments:30', 'orders:900001', 'orders:71', 'orders:50', 'orders:60', 'orders:40']
        summary = {
            'case_id': case_id, 'engine_revision': ENGINE_REVISION, 'include_deleted': False,
            'validation_scope': 'Real extraction tools and desktop analysis backend; test device-verification port for an isolated local examiner. GUI and native device verification are not exercised.',
            'elapsed_import_analysis_read_seconds': elapsed, 'pipeline_seconds': pipeline_seconds(run['stages']),
            'physical_rows': len(view['tables']['physical_records']),
            'decoded_row_events': len(view['tables']['binlog_events']),
            'transactions': len(analysis['grouping']['transactions']),
            'record_counts': dict(Counter(r['rollup'] for r in recon['records'])),
            'field_counts': dict(Counter(r['result'] for r in recon['rows'])),
            'coverage': analysis['grouping']['coverage'], 'stages': run['stages'],
            'acceptance_checks': checks, 'acceptance_passed': all(checks.values()),
            'selected_records': {key: records[key] for key in selected},
            'non_exact_records': [r for r in recon['records'] if r['rollup'] != 'Exact'],
            'findings': view['findings'], 'adapter_warnings': view['tables']['warnings'],
            'finding_rule_counts': dict(sorted(rule_counts.items())),
        }
        (source / 'OBSERVED_RESULTS.json').write_text(json.dumps(summary, indent=2, default=_json_default)+'\n', encoding='utf-8')
        text = '# Observed backend results\n\n'
        text += f"Acceptance passed: **{all(checks.values())}**. Engine revision: {ENGINE_REVISION}. Deleted-row extraction: off.\n\n"
        text += f"Import, analysis and result retrieval: **{elapsed} seconds**; pipeline stages: **{summary['pipeline_seconds']} seconds**. These are local backend measurements, not a timed GUI rehearsal.\n\n"
        text += summary['validation_scope'] + '\n\n'
        text += f"Physical rows: {summary['physical_rows']}. Decoded row events: {summary['decoded_row_events']}. Committed/grouped transactions: {summary['transactions']}.\n\n"
        text += '## Record classifications\n\n| Result | Records |\n|---|---:|\n'
        text += ''.join(f'| {kind} | {count} |\n' for kind, count in summary['record_counts'].items())
        text += '\n## Field/presence comparisons\n\n| Result | Comparisons |\n|---|---:|\n'
        text += ''.join(f'| {kind} | {count} |\n' for kind, count in summary['field_counts'].items())
        text += '\nCounts of records, comparison rows and findings measure different things; do not add them together.\n\n## Selected records\n\n| Record | Rollup |\n|---|---|\n'
        text += ''.join(f"| {key} | {records[key]['rollup']} |\n" for key in selected)
        text += '\n## Every non-Exact comparison\n\n| Record | Field | Log | Physical | Result |\n|---|---|---|---|---|\n'
        def cell(value):
            return str(value).replace('|', '\\|').replace('\n', ' ')
        for row in recon['rows']:
            if row['result'] != 'Exact':
                text += '| ' + ' | '.join(cell(row.get(k, '')) for k in ('record_id', 'field', 'log_display', 'phys_display', 'result')) + ' |\n'
        text += '\n## Every finding rule emitted\n\n| Rule | Title | Occurrences |\n|---|---|---:|\n'
        text += ''.join(f'| {rule} | {RULES[rule].title} | {count} |\n' for rule, count in sorted(rule_counts.items()))
        text += '\n## Acceptance checks\n\n' + ''.join(f"- {'PASS' if passed else 'FAIL'}: {name}\n" for name, passed in checks.items())
        text += '\nThe JSON companion contains all finding instances, adapter warnings, coverage, stage timings, selected records and every non-Exact record. Original SQL states the ground truth independently of this output.\n'
        (source / 'OBSERVED_RESULTS.md').write_text(text, encoding='utf-8')
        print(json.dumps({k: summary[k] for k in ('pipeline_seconds', 'record_counts', 'field_counts', 'acceptance_checks')}, indent=2), flush=True)
        if not all(checks.values()):
            raise AssertionError([name for name, passed in checks.items() if not passed])
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
