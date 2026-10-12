"""Read-only preview/full projection measurements for a saved case."""
import argparse
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.persistence.sqlite_pipeline_repository import SqlitePipelineRepository
from sidecar.views import case_preview, case_view
from sidecar.protocol import _json_default


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    parser.add_argument('--preview-output')
    args = parser.parse_args()
    connection = sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    # Do not run repository initialization/recovery against forensic source storage.
    pipelines = object.__new__(SqlitePipelineRepository)
    pipelines.connection = connection
    case_id = connection.execute('SELECT case_id FROM cases LIMIT 1').fetchone()[0]
    result = {}
    for label, project in [('preview', case_preview), ('full', case_view)]:
        times = []
        for _ in range(3):
            start = time.perf_counter()
            value = project(case_id, connection, None, pipelines)
            payload = json.dumps(value, default=_json_default, separators=(',', ':')).encode()
            times.append((time.perf_counter() - start) * 1000)
        result[label] = {'median_ms': round(statistics.median(times), 2), 'bytes': len(payload)}
        if label == 'preview' and args.preview_output:
            Path(args.preview_output).write_text(payload.decode(), encoding='utf-8')
    print(json.dumps(result))
    connection.close()
