"""Read-only desktop projections, using the same tagged values as case exports."""

import json

from adapters.persistence.case_export import _TABLES, _row
from adapters.persistence._reconciliation import check_storage, references
from core.application.errors import NotFoundError
from sidecar.commands import _pipeline_result
from core.domain.rules import RULES, describe
from core.engine import ENGINE_REVISION, ANALYSIS_FORMAT_VERSION


def case_preview(case_id, connection, stores, pipelines):
    """A consistent, bounded projection; analysis arrays stay inside SQLite."""
    connection.execute("SAVEPOINT case_preview")
    try:
        case = connection.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if case is None:
            raise NotFoundError(f"case not found: {case_id}")
        _compact_storage(connection, case_id)
        evidence = [_row(r) for r in connection.execute(
            "SELECT * FROM evidence_files WHERE case_id = ? ORDER BY evidence_id", (case_id,))]
        run = pipelines.latest_for_case(case_id)
        run_view = _pipeline_result(run) if run else None
        def length(stage, path):
            row = connection.execute("SELECT json_array_length(result_json, ?) FROM analysis_results WHERE case_id = ? AND stage = ?",
                                     (path, case_id, stage)).fetchone()
            return row[0] if row else None
        def count(table):
            return connection.execute(f"SELECT count(*) FROM {table} t JOIN evidence_files e ON e.evidence_id = t.evidence_id WHERE e.case_id = ?", (case_id,)).fetchone()[0]
        parsed = count('schemas')
        columns = connection.execute("SELECT count(*) FROM schema_columns c JOIN schemas s ON s.schema_id=c.schema_id JOIN evidence_files e ON e.evidence_id=s.evidence_id WHERE e.case_id=?", (case_id,)).fetchone()[0]
        integrity = connection.execute("SELECT count(*), sum(total_pages), sum(damaged_pages), sum(total_pages IS NULL), sum(status != 'valid') FROM integrity_results t JOIN evidence_files e ON e.evidence_id=t.evidence_id WHERE e.case_id=?", (case_id,)).fetchone()
        missing = connection.execute("SELECT count(DISTINCT j.value) FROM binlog_inventory t JOIN evidence_files e ON e.evidence_id=t.evidence_id, json_each(t.missing_files_json) j WHERE e.case_id=?", (case_id,)).fetchone()[0]
        comparisons = length('reconciliation', '$.rows')
        exact, unresolved = connection.execute("SELECT coalesce(sum(json_extract(j.value,'$.result')='Exact'),0), coalesce(sum(json_extract(j.value,'$.result')='Unresolved'),0) FROM analysis_results a, json_each(a.result_json,'$.rows') j WHERE a.case_id=? AND a.stage='reconciliation'", (case_id,)).fetchone()
        metrics = dict(evidence=len(evidence), verified=sum(e['verification_status']=='verified' for e in evidence),
                       tables=parsed if parsed or (run_view and any(s['stage'] == 'extract_schema' and s['status'] == 'succeeded' for s in run_view['stages'])) else None,
                       transactions=length('grouping', '$.transactions'), records=length('correlation', '$.records'),
                       exact=exact if comparisons is not None else None, unresolved=unresolved if comparisons is not None else None,
                       gaps=length('grouping', '$.coverage.gaps'))
        summaries = {
            'verify_evidence': f"{metrics['verified']} / {len(evidence)} match",
            'validate_pages': f"{'Unknown' if not integrity[0] or integrity[3] else integrity[1]} pages, {integrity[2] or 0} damaged",
            'extract_schema': f"{parsed} tables, {columns} columns",
            'extract_physical_rows': f"{count('physical_records')} rows",
            'decode_binary_logs': f"{sum(e['kind']=='binlog' for e in evidence)} logs, {missing} missing",
            'group_transactions': f"{metrics['transactions']} transactions",
            'correlate_records': f"{metrics['records']} records linked",
            'reconstruct_state': f"{length('reconstruction', '$.histories')} histories",
            'reconcile_records': f"{comparisons} comparisons",
        }
        return _present({'case': _row(case), 'evidence': evidence, 'run': _pipeline_result(run) if run else None,
                         'pipeline': {'metrics': metrics, 'summaries': summaries, 'warnings': {
                             'validate_pages': bool(integrity[4]), 'decode_binary_logs': bool(missing),
                             'group_transactions': bool(metrics['gaps'])}}})
    finally:
        connection.execute("RELEASE case_preview")


def _present(value):
    if type(value) is int and abs(value) > 2**53 - 1:
        return {"__integer__": str(value)}
    if isinstance(value, tuple):
        return [_present(item) for item in value]
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
                if value["rule_id"] in RULES:
                    finding["description"] = describe(value["rule_id"], value.get("context", {}))
                else:
                    finding.setdefault("description", value["rule_id"])
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
    tables["reports"] = [_row(row) for row in connection.execute(
        "SELECT * FROM reports WHERE case_id = ? ORDER BY created_at, report_id", (case_id,),
    )]
    counts["reports"] = len(tables["reports"])
    run = pipelines.latest_for_case(case_id)
    results = {}
    findings = {}
    for (stage,) in connection.execute("SELECT stage FROM analysis_results WHERE case_id = ?", (case_id,)):
        is_compact = stage == "reconciliation" and _compact_storage(connection, case_id)
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
            result["history_count"] = connection.execute(
                "SELECT json_array_length(result_json, '$.histories') FROM analysis_results WHERE case_id = ? AND stage = 'reconstruction'", (case_id,)).fetchone()[0]
            result["histories_paginated"] = True
        elif stage == "reconciliation":
            result["records"] = _project(connection, case_id, stage, "records",
                ("record", "rollup", "rollup_rule_id", "rollup_label", "triggers"),
                {"field_count": "json_array_length(j.value, '$.field_refs')" if is_compact
                 else "json_array_length(j.value, '$.fields')"})
            result["rows"] = _project(connection, case_id, stage, "rows",
                ("record_id", "field", "log_display", "phys_display", "result", "rule_id"))
            result["coverage"] = _part(connection, case_id, stage, "$.coverage")
        result["details_deferred"] = True
        results[stage] = result
        # The gaps view needs warnings and limitations. Routine informational
        # findings remain available in each selected record/transaction and export.
        findings_sql = (
            "WITH pool AS MATERIALIZED (SELECT p.key, p.value FROM analysis_results a, "
            "json_each(a.result_json, '$.finding_pool') p WHERE a.case_id=? AND a.stage=?) "
            "SELECT p.value, r.value, r.type FROM analysis_results a, "
            "json_each(a.result_json, '$.finding_refs') r "
            "LEFT JOIN pool p ON p.key=r.value WHERE a.case_id=? AND a.stage=? "
            "AND (json_extract(p.value, '$.severity') != 'info' OR p.value IS NULL "
            "OR r.type != 'integer' OR r.value < 0) ORDER BY r.key"
        ) if is_compact else (
            "SELECT j.value, NULL, NULL FROM analysis_results a, "
            "json_each(a.result_json, '$.findings') j "
            "WHERE a.case_id = ? AND a.stage = ? AND json_extract(j.value, '$.severity') != 'info'"
        )
        for value, ref, ref_type in connection.execute(
            findings_sql, (case_id, stage, case_id, stage) if is_compact else (case_id, stage),
        ):
            if is_compact and (ref_type != "integer" or ref < 0 or value is None):
                raise ValueError(f"finding_refs: invalid reference {ref!r}")
            _findings(json.loads(value), findings)
    return {
        "engine_revision": ENGINE_REVISION,
        "analysis_format_version": ANALYSIS_FORMAT_VERSION,
        "case": tables["cases"][0],
        "tables": _present(tables),
        "table_counts": counts,
        "analysis": _present(results),
        "findings": _present(list(findings.values())),
        "finding_rules": {
            rule_id: {"title": RULES[rule_id].title, "explanation": RULES[rule_id].statement,
                      "service": RULES[rule_id].service}
            for rule_id in sorted({finding["rule_id"] for finding in findings.values()})
            if rule_id in RULES
        },
        "run": _pipeline_result(run) if run else None,
    }


def _part(connection, case_id, stage, path):
    row = connection.execute(
        "SELECT json_extract(result_json, ?) FROM analysis_results WHERE case_id = ? AND stage = ?",
        (path, case_id, stage),
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def _compact_storage(connection, case_id):
    row = connection.execute(
        "SELECT json_extract(result_json, '$.storage_format'), "
        "json_extract(result_json, '$.storage_version'), "
        "json_type(result_json, '$.storage_format'), "
        "json_type(result_json, '$.storage_version') FROM analysis_results "
        "WHERE case_id=? AND stage='reconciliation'", (case_id,),
    ).fetchone()
    return _check_header(row)


def _check_header(row):
    if row is None or row[2] is None:
        return False
    if row[3] != "integer":
        raise ValueError("unsupported reconciliation storage version: expected integer")
    check_storage(row[0], row[1])
    return True


def _project(connection, case_id, stage, array, fields, extra=None):
    # All SQL fragments here are internal constants, never request values.
    pairs = [f"'{name}', json_extract(j.value, '$.{name}')" for name in fields]
    pairs.extend(f"'{name}', {sql}" for name, sql in (extra or {}).items())
    return [json.loads(row[0]) for row in connection.execute(
        f"SELECT json_object({', '.join(pairs)}) FROM analysis_results a, "
        "json_each(a.result_json, ?) j WHERE a.case_id = ? AND a.stage = ?",
        (f"$.{array}", case_id, stage),
    )]


def analysis_detail(connection, case_id, kind, identity, field=None, qualified_table=None):
    stage, array, path = {
        "history": ("reconstruction", "histories", "$.record.id"),
        "transaction": ("grouping", "transactions", "$.id"),
        "comparison": ("reconciliation", "rows", "$.record_id"),
    }[kind]
    # Resolve only this row's findings in the same statement: repeated full-document
    # reads for a header, pool size, and individual findings make detail queries slower.
    selection = "j.value"
    if kind == "comparison":
        selection += (
            ", json_extract(a.result_json, '$.storage_format'), "
            "json_extract(a.result_json, '$.storage_version'), "
            "json_type(a.result_json, '$.storage_format'), "
            "json_type(a.result_json, '$.storage_version'), "
            "json_array_length(a.result_json, '$.finding_pool'), "
            "(SELECT json_group_array(json(json_extract(a.result_json, "
            "'$.finding_pool[' || f.value || ']'))) "
            "FROM json_each(j.value, '$.finding_refs') f)"
        )
    row = connection.execute(
        f"SELECT {selection} FROM analysis_results a, json_each(a.result_json, ?) j "
        "WHERE a.case_id = ? AND a.stage = ? AND json_extract(j.value, ?) = ? "
        "AND (? IS NULL OR json_extract(j.value, '$.field') = ?) AND (? IS NULL OR json_extract(j.value, '$.record.table') = ?) LIMIT 1",
        (f"$.{array}", case_id, stage, path, identity, field, field, qualified_table, qualified_table),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"{kind} not found in this case: {identity}")
    detail = json.loads(row[0])
    if kind == "comparison" and _check_header(row[1:5]):
        refs = detail.pop("finding_refs")
        references(refs, range(row[5]), "comparison.finding_refs")
        detail["findings"] = json.loads(row[6])
    if kind == "history":
        return history_details(connection, case_id, [detail])[0]
    found = {}
    _findings(detail, found)
    return {"detail": _present(detail), "findings": _present(list(found.values()))}


def history_details(connection, case_id, histories):
    """Enrich a page in bounded, case-scoped batches using the detail projection."""
    references = [{tuple(step["ref"]) for step in history["steps"] if step.get("ref")} for history in histories]
    refs = sorted(set().union(*references)) if references else []
    events = {}
    for start in range(0, len(refs), 200):
        batch = refs[start:start + 200]
        values = ','.join('(?,?,?)' for _ in batch)
        parameters = [value for ref in batch for value in ref]
        for event in connection.execute(
            f"WITH refs(source_file, log_position, row_index) AS (VALUES {values}) "
            "SELECT b.* FROM refs r JOIN binlog_events b ON b.source_file=r.source_file "
            "AND b.log_position=r.log_position AND b.row_index=r.row_index "
            "JOIN evidence_files e ON e.evidence_id=b.evidence_id WHERE e.case_id=? ORDER BY b.event_id",
            [*parameters, case_id],
        ):
            item = _row(event)
            item["database"] = item.pop("database_name")
            item["table"] = item.pop("table_name")
            events.setdefault((item["source_file"], item["log_position"], item["row_index"]), item)
    result = []
    for history, references_for_history in zip(histories, references):
        history["events"] = [events[ref] for ref in sorted(references_for_history) if ref in events]
        found = {}
        _findings(history, found)
        result.append({"detail": _present(history), "findings": _present(list(found.values()))})
    return result
