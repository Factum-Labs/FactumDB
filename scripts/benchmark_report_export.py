"""Reproducible local report benchmark; no AWS resources or real case data.

Run with the project's Python and PDF dependencies on PYTHONPATH:
  py -3 scripts/benchmark_report_export.py --target-mb 800

Setup and each profile run in separate processes so fixture allocation cannot
inflate export memory measurements. The baseline is written incrementally in
the existing pretty-printed v2 shape; it is not loaded into memory.
"""

import argparse
import ctypes
import json
import math
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

PAYLOAD = "evidence sample " * 512
WHEN = "2026-10-11T00:00:00.000000Z"


def record(number):
    identity = {"id": f"records:{number}", "database": "benchmark", "table": "benchmark.records",
        "key": f"id = {number}", "pk": str(number), "label": f"records {number}",
        "key_columns": ["id"], "key_values": [str(number)]}
    physical = PAYLOAD if number % 1000 else "changed " + PAYLOAD
    field = {"record_id": identity["id"], "field": "payload", "log": PAYLOAD, "phys": physical,
        "log_display": PAYLOAD, "phys_display": physical,
        "result": "Exact" if number % 1000 else "Conflicting", "rule_id": "R-RECON-001",
        "comparable": True, "findings": [], "provenance": {"log": [], "physical": {
            "evidence_id": "evidence", "tool_name": "ibd2sql", "tool_run_id": "run",
            "source_file": "records.ibd", "log_position": None, "row_index": None}, "transaction_id": None}}
    return {"record": identity, "fields": [field], "rollup": field["result"],
        "rollup_rule_id": "R-ROLL-001", "rollup_label": field["result"], "triggers": [], "findings": []}


def setup(folder, target_mb):
    from adapters.persistence.sqlite_database import open_case_database
    sample = len(json.dumps(record(1), indent=2).encode()) + len(json.dumps(record(1)["fields"][0], indent=2).encode())
    count = math.ceil(target_mb * 1024 * 1024 / sample)
    stage = folder / "stage.json"
    with stage.open("w", encoding="utf-8", newline="\n") as out:
        out.write('{"records":[')
        for number in range(1, count + 1):
            if number > 1:
                out.write(",")
            json.dump(record(number), out, separators=(",", ":"))
        out.write('],"rows":[')
        for number in range(1, count + 1):
            if number > 1:
                out.write(",")
            json.dump(record(number)["fields"][0], out, separators=(",", ":"))
        out.write('],"coverage":{"observed_files":[],"gaps":[],"inventory":null,"findings":[]},"findings":[]}')
    db = open_case_database(folder / "case.db")
    db.execute("PRAGMA cache_size=-2048")
    db.execute("INSERT INTO cases(case_id,case_name,examiner,workspace_path,created_at) VALUES ('benchmark','Synthetic export benchmark','Test',?,?)", (str(folder), WHEN))
    db.execute("INSERT INTO evidence_files(evidence_id,case_id,kind,filename,source_path,size_bytes,source_sha256,verification_status,registered_at) VALUES ('evidence','benchmark','ibd','records.ibd','synthetic',0,?,'verified',?)", ("a" * 64, WHEN))
    db.execute("INSERT INTO tool_runs(tool_run_id,case_id,evidence_id,tool_name,tool_version,executable_path,executable_sha256,arguments_json,status,started_at) VALUES ('run','benchmark','evidence','ibd2sql','synthetic','synthetic',?,'[]','succeeded',?)", ("b" * 64, WHEN))
    for number in range(1, count + 1):
        db.execute("INSERT INTO physical_records VALUES (?,?,?,?,?,?,0,NULL,NULL)",
            (f"physical:{number}", "evidence", "run", "benchmark", "records", json.dumps({"id": number, "payload": record(number)["fields"][0]["phys"]})))
    # The blob is filled before validation; this is a disposable synthetic DB.
    db.execute("PRAGMA ignore_check_constraints=ON")
    db.execute("INSERT INTO analysis_results VALUES ('benchmark','reconciliation',CAST(zeroblob(?) AS TEXT),?)", (stage.stat().st_size, WHEN))
    rowid = db.execute("SELECT rowid FROM analysis_results").fetchone()[0]
    with db.blobopen("analysis_results", "result_json", rowid) as blob, stage.open("rb") as source:
        while chunk := source.read(65536):
            blob.write(chunk)
    db.execute("PRAGMA ignore_check_constraints=OFF")
    db.commit()
    assert db.execute("SELECT json_valid(result_json) FROM analysis_results").fetchone()[0] == 1
    # Write the legacy shape without materializing the large stage.
    from adapters.persistence.case_export import _TABLES, _row
    from adapters.persistence.investigator_export import analysis_members
    baseline = folder / "baseline-v2.json"
    with baseline.open("w", encoding="utf-8", newline="\n") as out:
        out.write('{"format":"factumdb-case-export","format_version":2,"tables":{')
        for index, (name, sql) in enumerate(_TABLES):
            if index:
                out.write(",\n")
            out.write(json.dumps(name) + ":[")
            if name == "analysis_results":
                out.write('{"case_id":"benchmark","stage":"reconciliation","saved_at":' + json.dumps(WHEN) + ',"result":{')
                current = None
                is_array = False
                for member, ordinal, value, _ in analysis_members(db, "benchmark", "reconciliation"):
                    if member != current:
                        if current is not None:
                            out.write("]" if is_array else "")
                            out.write(",\n")
                        current, is_array = member, ordinal is not None
                        out.write(json.dumps(member) + ":" + ("[" if is_array else ""))
                    elif ordinal != -1:
                        out.write(",\n")
                    if ordinal != -1:
                        json.dump(value, out, indent=2)
                out.write(("]" if is_array else "") + "}}")
            else:
                for ordinal, row in enumerate(db.execute(sql, ("benchmark",))):
                    if ordinal:
                        out.write(",\n")
                    json.dump(_row(row), out, indent=2)
            out.write("]")
        out.write("}}\n")
    db.close()
    return {"records": count, "baseline_bytes": baseline.stat().st_size, "stage_bytes": stage.stat().st_size}


def peak_rss():
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return counters.PeakWorkingSetSize
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)


def run_profile(folder, profile):
    from adapters.persistence.investigator_export import prepare_projection
    db = sqlite3.connect(folder / "case.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA cache_size=-2048")
    tracemalloc.start()
    started = time.perf_counter()
    projection = prepare_projection(db, "benchmark", profile=profile)
    prepared = time.perf_counter() - started
    path = folder / (profile + ".json")
    with path.open("x", encoding="utf-8", newline="\n") as output:
        projection.write_json(output)
    # Trace memory during generation; font loading is measured separately.
    _, python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    generation_rss = peak_rss()
    started = time.perf_counter()
    projection.prepare_lines()
    first_preview = time.perf_counter() - started
    started = time.perf_counter()
    for _ in range(100):
        projection.page(min(2, projection.pages))
    page_ms = (time.perf_counter() - started) * 10
    result = {"profile": profile, "output_bytes": path.stat().st_size,
        "generation_seconds": round(prepared, 3), "python_peak_bytes": python_peak,
        "generation_peak_rss_bytes": generation_rss, "preview_preparation_seconds": round(first_preview, 3),
        "cached_page_ms": round(page_ms, 3), "preview_pages": projection.pages,
        "total_peak_rss_bytes": peak_rss()}
    projection.close()
    db.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-mb", type=int, default=800)
    parser.add_argument("--worker", choices=["setup", "investigator", "full"])
    parser.add_argument("--folder", type=Path)
    args = parser.parse_args()
    if args.worker:
        result = setup(args.folder, args.target_mb) if args.worker == "setup" else run_profile(args.folder, args.worker)
        print(json.dumps(result))
        return
    with tempfile.TemporaryDirectory(prefix="factumdb-export-benchmark-") as folder:
        results = []
        for worker in ("setup", "investigator", "full"):
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", worker,
                       "--folder", folder, "--target-mb", str(args.target_mb)]
            process = subprocess.run(command, check=True, capture_output=True, text=True)
            result = json.loads(process.stdout)
            results.append(result)
            print(json.dumps(result), flush=True)
        destination = ROOT / ".bundle-cache/report-export-benchmark.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
