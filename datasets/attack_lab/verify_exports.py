"""Verify JSON/CSV exports against a completed real desktop validation case."""
import csv
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / 'backend'))
from sidecar.desktop import DesktopRuntime
from verify_app import call


def main():
    subject = sys.argv[1] if len(sys.argv) > 1 else '06_clean_marketplace'
    runtime = DesktopRuntime(ROOT / '.validation-cases' / subject)
    destination = ROOT / '.scratch' / ('exports-' + uuid.uuid4().hex[:8])
    destination.mkdir()
    try:
        case = call(runtime, 'list_cases')[0]
        case_id = case['id']
        assert case['status'] == 'Analysed', case
        call(runtime, 'export_case', case_id=case_id, format='JSON', path=str(destination / 'case.json'))
        print('JSON export finished', flush=True)
        call(runtime, 'export_case', case_id=case_id, format='CSV', path=str(destination / 'csv'))
        print('CSV export finished', flush=True)
        document = json.loads((destination / 'case.json').read_text(encoding='utf-8'))
        assert document['format_version'] == document['analysis_format_version'] == document['engine_revision'] == 2
        tables = document['tables']
        references = {(e['source_file'], e['log_position'], e['row_index']) for e in tables['binlog_events']}
        assert len(references) == len(tables['binlog_events'])
        grouping = next(r['result'] for r in tables['analysis_results'] if r['stage'] == 'grouping')
        retained = {(g['event']['source_file'], g['event']['log_position'], g['event']['row_index'])
                    for t in grouping['transactions'] for g in t['events']}
        retained.update((u['event']['source_file'], u['event']['log_position'], u['event']['row_index']) for u in grouping['ungrouped_events'])
        assert retained == references
        rows = 0
        for file in (destination / 'csv').glob('events_*.csv'):
            with file.open(encoding='utf-8', newline='') as stream:
                reader = csv.DictReader(stream)
                assert 'row_index' in reader.fieldnames
                rows += sum(1 for _ in reader)
        assert rows == len(references)
        reconciliation = next(r['result'] for r in tables['analysis_results'] if r['stage'] == 'reconciliation')
        with (destination / 'csv' / 'reconciliation.csv').open(encoding='utf-8', newline='') as stream:
            assert sum(1 for _ in csv.DictReader(stream)) == len(reconciliation['rows'])
        assert 'engine revision: 2' in (destination / 'csv' / 'about.txt').read_text(encoding='utf-8')
        summary = {'subject': subject, 'passed': True, 'binlog_rows': len(references),
                   'record_count': len(reconciliation['records']), 'field_count': len(reconciliation['rows']),
                   'json_csv_row_counts_agree': True, 'row_references_preserved': True,
                   'formats_versioned': True}
        (destination / 'export_checks.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(summary), flush=True)
        print(f'Artifacts: {destination}', flush=True)
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
