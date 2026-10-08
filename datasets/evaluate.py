"""Evaluate FactumDB on the test datasets, for the evaluation tables.

Runs the whole system - the real tools, the real application services and a
SQLite case database - on each scenario's reference evidence, and compares
the result with the scenario's expected.json. Each scenario runs twice, each
time in a process of its own, so the two results can be compared for
repeatability and each run's memory is measured on its own.

    python3 datasets/evaluate.py --evidence ~/factumdb/evidence --out docs/evaluation-results.md

The evidence is never committed. Each file listed in expected.json is looked
for in <evidence>/<scenario>/ and then in <evidence>/, and checked against its
SHA-256 before the scenario runs. ibd2sql is found through
FACTUMDB_IBD2SQL_PATH, or the repository's .env file.
"""

import argparse
import hashlib
import json
import os
import platform
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

DATASETS = Path(__file__).resolve().parent
REPO = DATASETS.parent
sys.path.insert(0, str(REPO / "backend"))

AGREEMENT = {"Exact", "Strong"}
RESULT = "RESULT "      # marks the one line of stdout a run reports on


# ── Evidence ─────────────────────────────────────────────────────────────────


def scenarios():
    return sorted(p.parent.name for p in DATASETS.glob("*/expected.json"))


def expected_for(scenario):
    return json.loads((DATASETS / scenario / "expected.json").read_text())


def locate(scenario, root):
    """The reference files of a scenario, and anything that stops it from running."""
    found, problems = [], []
    for item in expected_for(scenario)["evidence"]:
        candidates = (root / scenario / item["file"], root / item["file"])
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            problems.append(f"{item['file']} not found")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            problems.append(f"{item['file']} is not the reference copy (SHA-256 differs)")
        else:
            found.append(path)
    return found, problems


def ibd2sql_path():
    if os.environ.get("FACTUMDB_IBD2SQL_PATH"):
        return os.environ["FACTUMDB_IBD2SQL_PATH"]
    env = REPO / ".env"
    for line in env.read_text().splitlines() if env.exists() else ():
        if line.startswith("FACTUMDB_IBD2SQL_PATH="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("FACTUMDB_IBD2SQL_PATH must point at ibd2sql's main.py")


# ── One run, in its own process ──────────────────────────────────────────────


class _MemoryPipelines:
    """Pipeline runs are kept in memory by the app as well, for now."""

    def __init__(self):
        self.runs = {}

    def save(self, run):
        self.runs[run.id] = run

    def get(self, run_id):
        return self.runs.get(run_id)

    def active_for_case(self, case_id):
        return next((r for r in self.runs.values() if r.case_id == case_id and not r.stopped), None)


class _NoProgress:
    def publish(self, progress):
        pass


def run_once(scenario, root):
    """The whole pipeline on one scenario, measured. Returns plain JSON data."""
    from adapters.filesystem import (
        FilesystemCaseWorkspace, FilesystemEvidenceInspector, FilesystemRawOutputStore,
        FilesystemWorkingCopyManager, Sha256FileHasher,
    )
    from adapters.persistence.sqlite_database import open_case_database
    from adapters.persistence.sqlite_integration import build_sqlite_application_stores
    from core.application.defaults import UtcClock, UuidGenerator
    from core.application.models import CreateCaseRequest, RegisterEvidenceRequest
    from core.application.use_cases.audit import ToolRunAuditService
    from sidecar.composition import (
        PipelineDependencies, build_application_services, build_tool_adapters,
    )

    baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    files, problems = locate(scenario, root)
    if problems:
        return {"problems": problems}

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        connection = open_case_database(str(work / "case.sqlite"))
        stores = build_sqlite_application_stores(connection)
        ids, clock, hasher = UuidGenerator(), UtcClock(), Sha256FileHasher()
        audit = ToolRunAuditService(stores.cases, stores.evidence, stores.tool_runs,
                                    FilesystemRawOutputStore(work), hasher, ids, clock)
        dependencies = PipelineDependencies(
            cases=stores.cases, evidence=stores.evidence, copies=FilesystemWorkingCopyManager(work),
            hasher=hasher, extraction=stores.extraction, normalizer=stores.normalizer,
            domain=stores.domain, pipelines=_MemoryPipelines(), progress=_NoProgress(),
            ids=ids, clock=clock,
        )
        tools = build_tool_adapters(stores.schemas_for_case, audit=audit,
                                    ibd2sql_path=ibd2sql_path(), include_deleted=True)
        app = build_application_services(dependencies, tools,
                                         workspaces=FilesystemCaseWorkspace(work),
                                         inspector=FilesystemEvidenceInspector())

        started = time.perf_counter()
        case = app.create_case.execute(CreateCaseRequest(scenario, "evaluation")).case
        for path in files:
            app.register_evidence.execute(RegisterEvidenceRequest(case.id, str(path)))
        run = app.pipeline.run_all(app.pipeline.start(case.id).id)
        wall = time.perf_counter() - started

        failed = [s for s in run.stages if s.status.value not in ("succeeded", "skipped")]
        if failed:
            return {"problems": [f"stage {failed[0].stage.value} {failed[0].status.value}"]}
        result = _measure(connection, stores, case.id, expected_for(scenario))
        connection.close()

    result["seconds"] = {
        "total": wall,
        "stages": {s.stage.value: (s.attempts[-1].finished_at - s.attempts[-1].started_at).total_seconds()
                   for s in run.stages},
    }
    result["memory_mb"] = {
        "baseline": baseline / 1024,
        "peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "largest_tool": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024,
    }
    return result


def _plain(value):
    from core.domain.models.values import UndecodableValue
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UndecodableValue):
        return "<binary>"
    if isinstance(value, bool):
        return int(value)
    return value


def _references(value):
    from core.domain.models.canonical import ProvenanceReference
    if isinstance(value, ProvenanceReference):
        return [value]
    if is_dataclass(value) and not isinstance(value, type):
        return [r for f in fields(value) for r in _references(getattr(value, f.name))]
    if isinstance(value, dict):
        return [r for v in value.values() for r in _references(v)]
    if isinstance(value, (tuple, list)):
        return [r for v in value for r in _references(v)]
    return []


def _measure(connection, stores, case_id, expected):
    from adapters.persistence.sqlite_physical_record_repository import SqlitePhysicalRecordRepository
    from core.domain.models.values import UNOBSERVED

    physical = SqlitePhysicalRecordRepository(connection)
    page_rows = {}
    for table, columns in expected["columns"].items():
        database, name = table.split(".")
        rows = physical.records_for(database, name, case_id=case_id)
        page_rows[table] = {
            kind: [[_plain(r.values.get(c)) for c in columns] for r in rows if r.is_deleted == deleted]
            for kind, deleted in (("live", False), ("deleted", True))
        }
    events = {}
    for db, table, kind, n in connection.execute(
            "SELECT database_name, table_name, event_type, COUNT(*) FROM binlog_events GROUP BY 1, 2, 3"):
        events.setdefault(f"{db}.{table}", {})[kind] = n

    grouping = stores.domain.load_grouping(case_id)
    correlation = stores.domain.load_correlation(case_id)
    reconstruction = stores.domain.load_reconstruction(case_id)
    reconciliation = stores.domain.load_reconciliation(case_id)

    records = {
        r.record.id: {"rollup": r.rollup.value,
                      "fields": {f.field: [f.result.value, f.log_display, f.phys_display] for f in r.fields}}
        for r in reconciliation.records
    }
    rows = [r for r in reconciliation.rows if not r.is_presence]
    runs = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT tool_run_id, tool_name, evidence_id FROM tool_runs WHERE case_id = ?", (case_id,))}
    references = _references((grouping, correlation, reconstruction, reconciliation))
    facts = {
        "page_rows": page_rows,
        "events": events,
        "committed": connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE status = 'committed'").fetchone()[0],
        "warnings": dict(connection.execute("SELECT code, COUNT(*) FROM warnings GROUP BY code").fetchall()),
        "coverage_complete": grouping.coverage.complete,
        "records": records,
    }
    return {
        **facts,
        "fingerprint": hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
        "stored_events": sum(n for kinds in events.values() for n in kinds.values()),
        "events_in_transactions": sum(len(t.events) for t in grouping.transactions),
        "events_linked": sum(1 for e in correlation.event_correlations if e.record_id),
        "provenance": {
            "log_observed": sum(1 for r in rows if r.log is not UNOBSERVED),
            "log_linked": sum(1 for r in rows if r.log is not UNOBSERVED and r.provenance.log),
            "page_observed": sum(1 for r in rows if r.phys is not UNOBSERVED),
            "page_linked": sum(1 for r in rows if r.phys is not UNOBSERVED and r.provenance.physical),
            "references": len(references),
            "references_right_run": sum(
                1 for p in references if runs.get(p.tool_run_id) == (p.tool_name, p.evidence_id)),
        },
        "tools": sorted({f"{row[0]} {row[1]}" for row in connection.execute(
            "SELECT DISTINCT tool_name, tool_version FROM tool_runs WHERE case_id = ?", (case_id,))}),
    }


# ── Comparing with the expected results ─────────────────────────────────────


def score(expected, run):
    """What one run got right, against the scenario's expected.json."""
    rows_total = rows_matched = 0
    for table, kinds in expected["page_rows"].items():
        for kind, wanted in kinds.items():
            got = Counter(json.dumps(r) for r in run["page_rows"][table][kind])
            want = Counter(json.dumps(r) for r in wanted)
            rows_total += sum(want.values())
            rows_matched += sum((got & want).values())
    kinds_total = kinds_matched = 0
    for table, kinds in expected["row_events"].items():
        for kind, n in kinds.items():
            kinds_total += 1
            kinds_matched += run["events"].get(table, {}).get(kind, 0) == n

    present = run["records"]
    identities = sum(
        1 for record_id, want in expected["records"].items()
        if record_id in present or want.get("may_be_merged_into") in present
    )
    fields_total = fields_right = records_right = 0
    alarms, missed, inconclusive, unsupported = [], [], [], []
    for record_id, want in expected["records"].items():
        got = present.get(record_id)
        if got is None:
            continue
        records_right += got["rollup"] in want["rollup"]
        for field, allowed in want["fields"].items():
            actual = got["fields"].get(field, [None])[0]
            fields_total += 1
            fields_right += actual in allowed
            where = f"{record_id} {field}"
            if actual == "Conflicting" and "Conflicting" not in allowed:
                alarms.append(where)
            if allowed == ["Conflicting"] and actual != "Conflicting":
                missed.append(where)
            if actual == "Unresolved" and set(allowed) <= AGREEMENT:
                inconclusive.append(where)
            if actual == "Unsupported" and "Unsupported" not in allowed:
                unsupported.append(where)
    conflicts_expected = sum(
        allowed == ["Conflicting"] for want in expected["records"].values() for allowed in want["fields"].values())
    return {
        "rows": (rows_matched, rows_total),
        "event_kinds": (kinds_matched, kinds_total),
        "committed": (run["committed"], expected["transactions"]["committed"]),
        "warnings_ok": run["warnings"] == expected["warnings"],
        "coverage_ok": run["coverage_complete"] == expected["coverage"]["complete"],
        "identities": (identities, len(expected["records"])),
        "fields": (fields_right, fields_total),
        "records": (records_right, sum(1 for r in expected["records"] if r in present)),
        "false_alarms": alarms,
        "missed_conflicts": missed,
        "conflicts_expected": conflicts_expected,
        "inconclusive": inconclusive,
        "wrongly_unsupported": unsupported,
    }


def golden_scores():
    """The domain engine on Yasiru's synthetic golden datasets, scored by his
    test_evaluation_metrics.py, so both tables sit in one report."""
    from tests.domain.test_evaluation_metrics import (
        Score, correlation_score, false_negatives, false_positives,
        reconciliation_score, transaction_score,
    )
    from tests.fixtures.datasets import ALL

    totals = {"transaction boundaries": Score(0, 0), "record correlation": Score(0, 0),
              "reconciliation": Score(0, 0)}
    positives = negatives = 0
    for dataset in ALL:
        totals["transaction boundaries"] += transaction_score(dataset)
        totals["record correlation"] += correlation_score(dataset)
        totals["reconciliation"] += reconciliation_score(dataset)
        positives += false_positives(dataset)
        negatives += false_negatives(dataset)
    return len(ALL), totals, positives, negatives


# ── The report ───────────────────────────────────────────────────────────────


def fraction(pair):
    done, total = pair
    return f"{done} / {total}" + ("" if total == 0 else f" ({100 * done / total:.0f}%)")


def listing(items):
    return f"{len(items)}" + (f" ({', '.join(items[:3])}{', ...' if len(items) > 3 else ''})" if items else "")


def report(results, golden):
    commit = "`" + (subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                                   capture_output=True, text=True).stdout.strip() or "unknown") + "`"
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                      capture_output=True, text=True).stdout.strip():
        commit += " with uncommitted changes"
    first = next((r[0] for r in results.values() if "problems" not in r[0]), {})
    lines = [
        "# Evaluation results",
        "",
        f"Generated by `datasets/evaluate.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
        f"at commit {commit}. Python {platform.python_version()}, SQLite {sqlite3.sqlite_version}, "
        f"{platform.system()} {platform.release()}.",
        f"Tools: {', '.join(first.get('tools', []))}.",
        "",
    ]
    skipped = {s: r[0]["problems"] for s, r in results.items() if "problems" in r[0]}
    ran = {s: r for s, r in results.items() if s not in skipped}
    scores = {s: score(expected_for(s), r[0]) for s, r in ran.items()}

    def table(title, header, row):
        lines.extend([f"## {title}", "", "| Scenario | " + " | ".join(header) + " |",
                      "|---|" + "---|" * len(header)])
        lines.extend(f"| {s} | " + " | ".join(row(s)) + " |" for s in ran)
        lines.append("")

    table("Extraction and decoding", ["Page rows as expected", "Row event counts as expected",
                                      "Committed transactions", "Warnings", "Binlog coverage"],
          lambda s: [fraction(scores[s]["rows"]), fraction(scores[s]["event_kinds"]),
                     f"{scores[s]['committed'][0]} (expected {scores[s]['committed'][1]})",
                     "as expected" if scores[s]["warnings_ok"] else "differ",
                     "as expected" if scores[s]["coverage_ok"] else "differs"])
    table("Transaction boundaries and record correlation",
          ["Row events placed in a transaction", "Records identified", "Row events linked to a record"],
          lambda s: [fraction((ran[s][0]["events_in_transactions"], ran[s][0]["stored_events"])),
                     fraction(scores[s]["identities"]),
                     fraction((ran[s][0]["events_linked"], ran[s][0]["stored_events"]))])
    table("Reconciliation", ["Field verdicts as expected", "Record verdicts as expected",
                             "False alarms", "Missed conflicts", "Inconclusive", "Wrongly unsupported"],
          lambda s: [fraction(scores[s]["fields"]), fraction(scores[s]["records"]),
                     listing(scores[s]["false_alarms"]),
                     f"{len(scores[s]['missed_conflicts'])} of {scores[s]['conflicts_expected']}",
                     listing(scores[s]["inconclusive"]), str(len(scores[s]["wrongly_unsupported"]))])
    table("Provenance", ["Observed log values linked to their event", "Observed page values linked to their row",
                         "References naming the right tool run"],
          lambda s: [fraction((ran[s][0]["provenance"]["log_linked"], ran[s][0]["provenance"]["log_observed"])),
                     fraction((ran[s][0]["provenance"]["page_linked"], ran[s][0]["provenance"]["page_observed"])),
                     fraction((ran[s][0]["provenance"]["references_right_run"],
                               ran[s][0]["provenance"]["references"]))])
    table("Repeatability", ["Two runs, separate processes"],
          lambda s: ["identical" if ran[s][0]["fingerprint"] == ran[s][1]["fingerprint"] else "DIFFERENT"])
    stages = list(first.get("seconds", {}).get("stages", {}))
    table("Processing time (seconds, first run)", ["Whole case", *stages],
          lambda s: [f"{ran[s][0]['seconds']['total']:.2f}",
                     *(f"{ran[s][0]['seconds']['stages'][st]:.3f}" for st in stages)])
    table("Memory (MB, first run)", ["FactumDB before the run", "FactumDB at peak", "Largest tool process"],
          lambda s: [f"{ran[s][0]['memory_mb'][k]:.0f}" for k in ("baseline", "peak", "largest_tool")])

    count, totals, positives, negatives = golden
    lines.extend([f"## Domain engine on the {count} golden datasets", "",
                  "Scored by `backend/tests/domain/test_evaluation_metrics.py`.", "",
                  "| Measure | Result |", "|---|---|"])
    lines.extend(f"| {name} | {fraction((s.correct, s.total))} |" for name, s in totals.items())
    lines.extend([f"| false positives | {positives} |", f"| false negatives | {negatives} |", ""])
    for scenario, problems in skipped.items():
        lines.append(f"Not run: {scenario}: {'; '.join(problems)}.")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--evidence", type=Path, required=True,
                        help="folder holding the reference evidence")
    parser.add_argument("--out", type=Path, help="also write the report to this file")
    parser.add_argument("--run-one", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.evidence.expanduser()

    if args.run_one:
        print(RESULT + json.dumps(run_once(args.run_one, root)))
        return

    results = {}
    for scenario in scenarios():
        # TIMESTAMP values are shown in the time zone of the machine reading
        # them, so a scenario runs in the zone its expected values were read in.
        env = dict(os.environ)
        zone = expected_for(scenario).get("timestamp_time_zone")
        if zone:
            env["TZ"] = zone.split()[0]
        runs = []
        for _ in range(2):
            child = subprocess.run(
                [sys.executable, __file__, "--evidence", str(root), "--run-one", scenario],
                capture_output=True, text=True, env=env,
            )
            line = next((l for l in child.stdout.splitlines() if l.startswith(RESULT)), None)
            runs.append(json.loads(line[len(RESULT):]) if line else
                        {"problems": [child.stderr.strip().splitlines()[-1] if child.stderr.strip()
                                      else "the run reported nothing"]})
            if "problems" in runs[-1]:
                break
        results[scenario] = runs
    text = report(results, golden_scores())
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
