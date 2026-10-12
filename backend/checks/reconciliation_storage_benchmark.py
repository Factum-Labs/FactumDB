"""Compare internal legacy/compact storage on identical precomputed conclusions.

Run from backend: python checks/reconciliation_storage_benchmark.py --output results.json
No AWS resources or real evidence are used. All SQLite databases are temporary.
"""
import argparse
import gc
import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.persistence._reconciliation import decode_reconciliation, encode_reconciliation
from adapters.persistence._results import encode
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_pipeline_repository import SqlitePipelineRepository
from core.domain.models.case import Case
from sidecar.views import analysis_detail, case_preview
from tests.fixtures.builders import accounts_schema, ev, integrity, inventory, marker, phys
from tests.fixtures.datasets import Dataset
from tests.fixtures.pipeline import run_pipeline


def fixture(size, updates=0):
    events, physical = [], []
    for index in range(size):
        row = {"account_id": index + 1, "owner": "Synthetic", "balance": index,
               "status": "active"}
        events.append(ev("INSERT", 100 + len(events) * 100, after=row))
        for update in range(updates):
            after = {**row, "balance": index + update + 1}
            events.append(ev("UPDATE", 100 + len(events) * 100, before=row, after=after))
            row = after
        physical.append(phys("accounts", row, page_no=4 + index // 100,
                             page_offset=100 + index % 100 * 32))
    return Dataset(
        id="storage-benchmark", title="Synthetic storage", why="Storage comparison",
        schemas=(accounts_schema(),), events=tuple(events), physical=tuple(physical),
        markers=(marker("committed", 4, 100 + len(events) * 100,
                        event_positions=tuple(e.log_position for e in events), gtid_sequence=1),),
        inventory=inventory("binlog.000018"),
        integrity={("finance", "accounts"): integrity()},
        physical_tables=frozenset({("finance", "accounts")}),
    )


def timed(action):
    start = time.perf_counter()
    value = action()
    return value, (time.perf_counter() - start) * 1000


def benchmark(size, updates, repetitions):
    result = run_pipeline(fixture(size, updates)).reconciliation
    output = {"records": size, "updates_per_record": updates, "comparisons": len(result.rows),
              "repetitions": repetitions}
    with tempfile.TemporaryDirectory(prefix="factumdb-storage-") as directory:
        connection = open_case_database(str(Path(directory) / "case.sqlite"))
        try:
            SqliteCaseRepository(connection).save(Case(
                "benchmark", "Synthetic", "Benchmark", datetime.now(UTC), directory))
            pipelines = SqlitePipelineRepository(connection)
            samples = {name: {metric: [] for metric in
                              ("encoding_ms", "write_ms", "load_ms", "preview_ms", "detail_ms")}
                       for name in ("legacy", "compact")}
            row = result.rows[-1]
            expected_detail = encode(row)
            expected_preview = None
            # Alternate formats to reduce run-order bias; first iteration is warm-up.
            for repetition in range(repetitions + 1):
                names = ("legacy", "compact") if repetition % 2 == 0 else ("compact", "legacy")
                for name in names:
                    gc.collect()
                    codec = encode if name == "legacy" else encode_reconciliation
                    payload, encoding_ms = timed(lambda codec=codec: json.dumps(codec(result)))

                    def write(payload=payload):
                        with connection:
                            connection.execute(
                                "INSERT OR REPLACE INTO analysis_results VALUES (?,?,?,?)",
                                ("benchmark", "reconciliation", payload, "fixed"))

                    _, write_ms = timed(write)

                    def load():
                        text = connection.execute("SELECT result_json FROM analysis_results "
                                                  "WHERE case_id='benchmark'").fetchone()[0]
                        return decode_reconciliation(json.loads(text))

                    loaded, load_ms = timed(load)
                    assert loaded == result
                    del loaded
                    preview, preview_ms = timed(lambda: case_preview(
                        "benchmark", connection, None, pipelines))
                    if expected_preview is None:
                        expected_preview = preview
                    assert preview == expected_preview
                    detail, detail_ms = timed(lambda: analysis_detail(
                        connection, "benchmark", "comparison", row.record_id, row.field))
                    assert detail["detail"] == expected_detail
                    if repetition:
                        measurements = (encoding_ms, write_ms, load_ms, preview_ms, detail_ms)
                        for metric, value in zip(samples[name], measurements, strict=True):
                            samples[name][metric].append(value)
                    output.setdefault(name, {})["json_bytes"] = len(payload.encode())
                    print(f"{size} records, {updates} updates: {name} repetition {repetition}",
                          file=sys.stderr, flush=True)
            for name, metrics in samples.items():
                output[name].update({key: round(statistics.median(values), 3)
                                     for key, values in metrics.items()})
            output["compact_vs_legacy"] = {
                key: round(output["compact"][key] / value, 4)
                for key, value in output["legacy"].items()
            }
        finally:
            connection.close()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    results = [benchmark(size, updates, args.repetitions)
               for size, updates in ((2500, 0), (10000, 0), (250, 40))]
    text = json.dumps(results, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
