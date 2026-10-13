"""Time complete report preparation on a disposable backup of a saved case."""
import argparse
import json
import sqlite3
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_database import initialise
from sidecar.protocol import SidecarRequest
from tests.application.auth_support import authenticated_runtime


def run(database, formats):
    with tempfile.TemporaryDirectory(prefix="factumdb-report-benchmark-") as temporary:
        root = Path(temporary)
        runtime = authenticated_runtime(root)
        try:
            source = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
            case_id = source.execute("SELECT case_id FROM cases LIMIT 1").fetchone()[0]
            directory = root / "cases" / case_id
            directory.mkdir(parents=True)
            copied = sqlite3.connect(directory / "case.db")
            source.backup(copied)
            source.close()
            copied.row_factory = sqlite3.Row
            initialise(copied)
            case = replace(SqliteCaseRepository(copied).get(case_id), workspace_path=str(directory))
            SqliteCaseRepository(copied).save(case)
            copied.close()
            runtime.cases.save(case)
            runtime.ownership.assign(case_id, runtime.auth.require_actor()["actor_id"])
            router = runtime.router()

            def invoke(command, payload):
                response = router.dispatch(SidecarRequest("benchmark", command, payload))
                if not response.ok:
                    raise RuntimeError((command, response.error_code, response.error_message))
                return response.result

            for kind in ("transactions", "histories", "reconciliation", "finding_groups", "warning_groups", "tool_runs", "reports"):
                invoke("get_screen_page", dict(case_id=case_id, kind=kind, offset=0, limit=100))
            for kind in ("report", "analysis", "pdf"):
                invoke("warm_dependencies", dict(kind=kind))
            times = {format: [] for format in formats}
            complete = {}
            page_max = 0
            started = time.perf_counter()
            while len(complete) < len(times):
                for format in times:
                    if format in complete:
                        continue
                    before = time.perf_counter()
                    result = invoke("prepare_background_report", dict(case_id=case_id, format=format))
                    times[format].append(time.perf_counter() - before)
                    if len(times[format]) % 200 == 0:
                        before = time.perf_counter()
                        invoke("get_screen_page", dict(case_id=case_id, kind="transactions", offset=0, limit=100))
                        page_max = max(page_max, time.perf_counter() - before)
                    if "preview_token" in result:
                        complete[format] = dict(elapsed_seconds=round(time.perf_counter() - started, 3), bytes=result["size_bytes"], pages=result["pages"])
                        print(json.dumps({"ready": format, **complete[format]}), flush=True)
            for format, durations in times.items():
                print(json.dumps(dict(format=format, work_seconds=round(sum(durations), 3), batches=len(durations), max_batch_ms=round(max(durations) * 1000, 2))), flush=True)
                before = time.perf_counter()
                assert invoke("claim_background_report", dict(case_id=case_id, format=format, redacted=True))
                print(json.dumps(dict(claim=format, ms=round((time.perf_counter() - before) * 1000, 2))), flush=True)
            print(json.dumps(dict(max_interleaved_page_ms=round(page_max * 1000, 2))), flush=True)
        finally:
            runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--formats", nargs="+", choices=("PDF", "JSON"), default=["PDF", "JSON"])
    args = parser.parse_args()
    run(args.database, args.formats)
