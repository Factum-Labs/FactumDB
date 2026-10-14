"""Deterministic synthetic engine workload; no real forensic evidence is uploaded."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


def run(size):
    from tests.fixtures.builders import accounts_schema, ev, integrity, inventory, marker, phys
    from tests.fixtures.datasets import Dataset
    from tests.fixtures.pipeline import run_pipeline
    from core.domain.models.serialization import to_readable_json

    before = time.perf_counter()
    events, records = [], []
    for index in range(size):
        row = {'account_id': index + 1, 'owner': 'Synthetic', 'balance': index,
               'status': 'active'}
        position = 100 + index * 100
        events.append(ev('INSERT', position, after=row))
        records.append(phys('accounts', row, page_no=4 + index // 100,
                            page_offset=100 + index % 100 * 32))
    dataset = Dataset(id='benchmark', title='Synthetic committed inserts',
                      why='Scale deterministic matching log and physical records without personal data.',
                      schemas=(accounts_schema(),), events=tuple(events), physical=tuple(records),
                      markers=(marker('committed', 4, 100 + size * 100,
                                      event_positions=tuple(e.log_position for e in events),
                                      gtid_sequence=1),),
                      inventory=inventory('binlog.000018'),
                      integrity={('finance', 'accounts'): integrity()},
                      physical_tables=frozenset({('finance', 'accounts')}))
    generated = time.perf_counter()
    result = run_pipeline(dataset)
    analyzed = time.perf_counter()
    if len(result.correlation.records) != size or len(result.reconciliation.records) != size:
        raise RuntimeError('Incorrect record count in synthetic workload')
    # Serialize the record/graph projection, not nested pipeline internals that can
    # repeat the same transaction context for every record. Real report export is
    # a separate packaged workflow; label this projection explicitly.
    projection = {'records': [{'id': entry.record.id, 'rollup': entry.rollup,
                              'fields': [{'field': field.field, 'log': field.log,
                                          'phys': field.phys, 'result': field.result,
                                          'rule_id': field.rule_id} for field in entry.fields]}
                             for entry in result.reconciliation.records],
                  'edges': result.correlation.edges}
    encoded = to_readable_json(projection).encode('utf-8')
    return {'rows': size, 'fixture_seconds': generated-before,
            'analysis_seconds': analyzed-generated,
            'serialization_seconds': time.perf_counter()-analyzed,
            'output_bytes': len(encoded), 'output_sha256': hashlib.sha256(encoded).hexdigest(),
            'serialization_scope': 'compact record conclusions and graph edges; excludes UI and full report export',
            'correlated_records': len(result.correlation.records),
            'reconciled_records': len(result.reconciliation.records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, required=True)
    parser.add_argument('--backend', type=Path)
    options = parser.parse_args()
    if not 1 <= options.rows <= 100000:
        parser.error('Rows must be between 1 and 100000')
    if options.backend:
        sys.path.insert(0, str(options.backend.resolve()))
    print(json.dumps(run(options.rows)))


if __name__ == '__main__':
    main()
