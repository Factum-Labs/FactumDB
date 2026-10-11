"""Measure legacy and bundled pages on a disposable copy of a saved case."""
import argparse
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_history_summary_repository import HistorySummaries
from sidecar.views import analysis_detail


def measure(connection, case_id, label, page_output=None):
    repo = HistorySummaries(connection)
    repo.ensure(case_id)
    legacy_times, bundle_times = [], []
    for _ in range(5):
        start = time.perf_counter()
        old = repo.page(case_id)
        single = analysis_detail(connection, case_id, 'history', old['items'][0]['record']['id'], qualified_table=old['items'][0]['record']['table'])
        legacy_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        bundle = repo.page(case_id, include_details=True)
        bundle_times.append((time.perf_counter() - start) * 1000)
    print(json.dumps(dict(fixture=label, total=old['total'], page=len(bundle['items']), legacy_ms=round(statistics.median(legacy_times), 2), bundled_ms=round(statistics.median(bundle_times), 2), legacy_bytes=len(json.dumps([old, single]).encode()), bundled_bytes=len(json.dumps(bundle).encode()))))
    if page_output:
        Path(page_output).write_text(json.dumps(bundle), encoding='utf-8')
        for offset in (100, 200):
            path = Path(page_output)
            path.with_name(f'{path.stem}-{offset}{path.suffix}').write_text(json.dumps(repo.page(case_id, offset=offset, include_details=True)), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    parser.add_argument('--page-output', help='Optional JSON page for browser memory measurements')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='factumdb-history-benchmark-') as directory:
        target = Path(directory) / 'case.db'
        # Include committed WAL contents without touching the source database.
        source = sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        connection = open_case_database(target)
        case_id = connection.execute('SELECT case_id FROM cases LIMIT 1').fetchone()[0]
        measure(connection, case_id, 'credit-union saved case', args.page_output)
        history = json.loads(connection.execute("SELECT result_json FROM analysis_results WHERE case_id=? AND stage='reconstruction'", (case_id,)).fetchone()[0])['histories'][0]
        history['steps'] = history['steps'] * 100
        histories = []
        for index in range(100):
            record = {**history['record'], 'id': f'long:{index}'}
            histories.append({**history, 'record': record})
        with connection:
            connection.execute("UPDATE analysis_results SET result_json=? WHERE case_id=? AND stage='reconstruction'", (json.dumps({'histories': histories}), case_id))
        measure(connection, case_id, '100 histories with 100x steps')
        connection.close()
