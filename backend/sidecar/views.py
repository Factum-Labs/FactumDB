"""Read-only desktop projections, using the same tagged values as case exports."""

import json

from adapters.persistence.case_export import _TABLES, _row
from core.application.errors import NotFoundError
from sidecar.commands import _pipeline_result
from core.domain.rules import describe
from core.engine import ENGINE_REVISION, ANALYSIS_FORMAT_VERSION


def _present(value):
    if type(value) is int and abs(value) > 2**53 - 1:
        return {"__integer__": str(value)}
    if isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = _present(item)
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = _present(item)
        return value
    return value


def _findings(value, found):
    if isinstance(value, dict):
        if "rule_id" in value and "subject" in value and "severity" in value:
            key = (value['rule_id'], value['severity'], json.dumps(value['subject'], sort_keys=True),
                   json.dumps(value.get('context', {}), sort_keys=True),
                   json.dumps(value.get('provenance', []), sort_keys=True))
            if key not in found:
                finding = dict(value)
                finding["description"] = describe(value["rule_id"], value.get("context", {}))
                found[key] = finding
            return
        for item in value.values():
            _findings(item, found)
    elif isinstance(value, list):
        for item in value:
            _findings(item, found)


def case_view(case_id, connection, stores, pipelines):
    # Export is an archival format, not a desktop view. In particular, histories
    # and reconciliation duplicate their findings in several nested structures.
    # Project in SQLite so opening a case never builds those entire trees.
    large = {"physical_records", "binlog_events", "transactions", "transaction_events",
             "analysis_results"}
    tables, counts = {}, {}
    for name, sql in _TABLES:
        count_sql = sql.split(" ORDER BY ", 1)[0]
        counts[name] = connection.execute(f"SELECT count(*) FROM ({count_sql})", (case_id,)).fetchone()[0]
        tables[name] = [] if name in large else [_row(row) for row in connection.execute(sql, (case_id,))]
    if not tables["cases"]:
        raise NotFoundError(f"case not found: {case_id}")
    tables["pipeline_runs"] = [_row(row) for row in connection.execute(
        "SELECT * FROM pipeline_runs WHERE case_id = ? ORDER BY rowid", (case_id,))]
    counts["pipeline_runs"] = len(tables["pipeline_runs"])
    run = pipelines.latest_for_case(case_id)
    results = {}
    findings = {}
    for (stage,) in connection.execute("SELECT stage FROM analysis_results WHERE case_id = ?", (case_id,)):
        result = {}
        if stage == "grouping":
            result["transactions"] = _project(connection, case_id, stage, "transactions",
                ("id", "status", "source_file", "start_position", "commit_timestamp"),
                {"event_count": "json_array_length(j.value, '$.events')"})
            result["coverage"] = _part(connection, case_id, stage, "$.coverage")
        elif stage == "correlation":
            result["records"] = _project(connection, case_id, stage, "records", ("record", "method"))
            result["edges"] = _project(connection, case_id, stage, "edges", ("tx_id", "record_id", "event_type"))
        elif stage == "reconstruction":
            result["histories"] = _project(connection, case_id, stage, "histories", ("record", "method"),
                {"step_count": "json_array_length(j.value, '$.steps')"})
        elif stage == "reconciliation":
            result["rows"] = _project(connection, case_id, stage, "rows",
                ("record_id", "field", "log_display", "phys_display", "result", "rule_id"))
            result["coverage"] = _part(connection, case_id, stage, "$.coverage")
        result["details_deferred"] = True
        results[stage] = result
        # The gaps view needs warnings and limitations. Routine informational
        # findings remain available in each selected record/transaction and export.
        for (value,) in connection.execute(
            "SELECT j.value FROM analysis_results a, "
            "json_each(a.result_json, '$.findings') j "
            "WHERE a.case_id = ? AND a.stage = ? AND json_extract(j.value, '$.severity') != 'info'",
            (case_id, stage),
        ):
            _findings(json.loads(value), findings)
    return {
        "engine_revision": ENGINE_REVISION,
        "analysis_format_version": ANALYSIS_FORMAT_VERSION,
        "case": tables["cases"][0],
        "tables": _present(tables),
        "table_counts": counts,
        "analysis": _present(results),
        "findings": _present(list(findings.values())),
        "run": _pipeline_result(run) if run else None,
    }


def _part(connection, case_id, stage, path):
    row = connection.execute(
        "SELECT json_extract(result_json, ?) FROM analysis_results WHERE case_id = ? AND stage = ?",
        (path, case_id, stage),
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def _project(connection, case_id, stage, array, fields, extra=None):
    # All SQL fragments here are internal constants, never request values.
    pairs = [f"'{name}', json_extract(j.value, '$.{name}')" for name in fields]
    pairs.extend(f"'{name}', {sql}" for name, sql in (extra or {}).items())
    return [json.loads(row[0]) for row in connection.execute(
        f"SELECT json_object({', '.join(pairs)}) FROM analysis_results a, "
        "json_each(a.result_json, ?) j WHERE a.case_id = ? AND a.stage = ?",
        (f"$.{array}", case_id, stage),
    )]


def analysis_detail(connection, case_id, kind, identity, field=None):
    stage, array, path = {
        "history": ("reconstruction", "histories", "$.record.id"),
        "transaction": ("grouping", "transactions", "$.id"),
        "comparison": ("reconciliation", "rows", "$.record_id"),
    }[kind]
    row = connection.execute(
        "SELECT j.value FROM analysis_results a, json_each(a.result_json, ?) j "
        "WHERE a.case_id = ? AND a.stage = ? AND json_extract(j.value, ?) = ? "
        "AND (? IS NULL OR json_extract(j.value, '$.field') = ?) LIMIT 1",
        (f"$.{array}", case_id, stage, path, identity, field, field),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"{kind} not found in this case: {identity}")
    detail = json.loads(row[0])
    if kind == "history":
        refs = {tuple(step["ref"]) for step in detail["steps"] if step.get("ref")}
        events = []
        for ref in sorted(refs):
            event = connection.execute(
                "SELECT * FROM binlog_events WHERE source_file = ? AND log_position = ? AND row_index = ?",
                ref,
            ).fetchone()
            if event:
                item = _row(event)
                item["database"] = item.pop("database_name")
                item["table"] = item.pop("table_name")
                events.append(item)
        detail["events"] = events
    found = {}
    _findings(detail, found)
    return {"detail": _present(detail), "findings": _present(list(found.values()))}
