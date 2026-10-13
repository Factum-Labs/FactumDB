"""Compare old projections and progressive reads on a temporary SQLite backup.

The supplied forensic database is opened read-only and never migrated or edited.
"""
import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.persistence.sqlite_database import initialise
from adapters.persistence.sqlite_pipeline_repository import SqlitePipelineRepository
from adapters.persistence.sqlite_screen_repository import ScreenRepository
from sidecar.views import case_preview, case_view
from sidecar.protocol import _json_default


def measure(fetch, iterations=3):
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        value = fetch()
        payload = json.dumps(value, default=_json_default, separators=(',', ':')).encode()
        times.append((time.perf_counter() - start) * 1000)
    return dict(median_ms=round(statistics.median(times), 2), bytes=len(payload))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='factumdb-screen-benchmark-') as directory:
        source = sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)
        c = sqlite3.connect(Path(directory) / 'case.db')
        source.backup(c); source.close()
        c.row_factory = sqlite3.Row
        initialise(c)
        pipelines = object.__new__(SqlitePipelineRepository); pipelines.connection = c
        case_id = c.execute('SELECT case_id FROM cases LIMIT 1').fetchone()[0]
        repository = ScreenRepository(c)
        old = dict(preview=measure(lambda: case_preview(case_id, c, None, pipelines)), full=measure(lambda: case_view(case_id, c, None, pipelines)))
        result = dict(previous=old, initial_header=measure(lambda: case_preview(case_id, c, None, pipelines, fast=True)), cold_pages={})
        for kind in ('transactions', 'histories', 'reconciliation'):
            result['cold_pages'][kind] = measure(lambda: repository.page(case_id, kind), 1)
        result['cold_pages']['finding_groups'] = measure(lambda: repository.groups(case_id), 1)
        result['header'] = measure(lambda: case_preview(case_id, c, None, pipelines, fast=True))
        result['warm_pages'] = {kind: measure(lambda kind=kind: repository.page(case_id, kind)) for kind in ('transactions', 'histories', 'reconciliation')}
        result['warm_pages']['finding_groups'] = measure(lambda: repository.groups(case_id))
        result['all_first_pages_ms'] = round(result['initial_header']['median_ms'] + sum(value['median_ms'] for value in result['cold_pages'].values()), 2)
        print(json.dumps(result, indent=2))
        c.close()
        assert result['initial_header']['median_ms'] <= old['preview']['median_ms'], 'Header regression'
        assert result['header']['median_ms'] <= old['preview']['median_ms'], 'Header regression'
        assert all(v['median_ms'] <= old['full']['median_ms'] for v in result['cold_pages'].values()), 'Cold page regression'
        assert result['all_first_pages_ms'] <= old['full']['median_ms'], 'Combined first-page regression'
