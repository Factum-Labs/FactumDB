"""Desktop requests must not serialize the full archival analysis trees."""
import json

from adapters.persistence._results import encode
from adapters.persistence.case_export import case_export
from tests.application.test_desktop_runtime import create, call, response, evidence, tools, finish
from tests.application.auth_support import authenticated_runtime as DesktopRuntime
from tests.fixtures.datasets import DS02
from tests.fixtures.pipeline import run_pipeline
from core.domain.rules import RULES
from sidecar.views import _findings


def test_overview_defers_complete_details_without_changing_exports(tmp_path):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        other = create(runtime, "Other")
        connection, stores, _ = runtime.session(case_id)
        result = run_pipeline(DS02)
        for stage in ("grouping", "correlation", "reconstruction", "reconciliation"):
            getattr(stores.domain, "save_" + stage)(case_id, getattr(result, stage))
        archive = case_export(connection, case_id)
        view = call(runtime, "get_case_data", case_id=case_id)
        assert view["tables"]["analysis_results"] == []
        assert view["table_counts"]["analysis_results"] == 4
        expected_rules = {finding["rule_id"] for finding in view["findings"] if finding["rule_id"] in RULES}
        assert set(view["finding_rules"]) == expected_rules
        for rule_id, metadata in view["finding_rules"].items():
            definition = RULES[rule_id]
            assert metadata == {"title": definition.title, "explanation": definition.statement, "service": definition.service}
        assert len(json.dumps(view)) < len(json.dumps(archive)) / 3
        assert "histories" not in view["analysis"]["reconstruction"]
        assert view["analysis"]["reconstruction"]["history_count"] == len(result.reconstruction.histories)
        assert "steps" not in call(runtime, "get_history_page", case_id=case_id)["items"][0]
        assert "events" not in view["analysis"]["grouping"]["transactions"][0]
        assert "findings" not in view["analysis"]["reconciliation"]["rows"][0]
        record_summaries = view["analysis"]["reconciliation"]["records"]
        assert len(record_summaries) == len(result.reconciliation.records)
        for summary, record in zip(record_summaries, result.reconciliation.records):
            assert summary["record"] == encode(record.record)
            assert summary["rollup"] == record.rollup.value
            assert summary["rollup_rule_id"] == record.rollup_rule_id
            assert summary["rollup_label"] == record.rollup_label
            assert summary["field_count"] == len(record.fields)
            assert "fields" not in summary
        history = result.reconstruction.histories[0]
        detail = call(runtime, "get_analysis_detail", case_id=case_id, kind="history", identity=history.record.id, qualified_table=history.record.table)
        assert {k: v for k, v in detail["detail"].items() if k != "events"} == encode(history)
        assert detail["findings"] and all("description" in f for f in detail["findings"])
        tx = result.grouping.transactions[0]
        assert call(runtime, "get_analysis_detail", case_id=case_id, kind="transaction", identity=tx.id)["detail"] == encode(tx)
        row = result.reconciliation.rows[0]
        assert call(runtime, "get_analysis_detail", case_id=case_id, kind="comparison", identity=row.record_id, field=row.field)["detail"] == encode(row)
        assert response(runtime, "get_analysis_detail", case_id=other, kind="history", identity=history.record.id)["error_code"] == "NotFoundError"
        assert not response(runtime, "get_analysis_detail", case_id=case_id, kind="unknown", identity="anything")["ok"]
        assert case_export(connection, case_id)["tables"] == archive["tables"]
    finally:
        runtime.close()


def test_unknown_findings_remain_visible_and_deduplication_is_preserved():
    unknown = {"rule_id": "R-FUTURE-001", "severity": "warning",
               "subject": {"kind": "record", "id": "visits:50"},
               "description": "Original saved description", "context": {"record": "visits:50"}, "provenance": []}
    found = {}
    _findings([unknown, dict(unknown)], found)
    assert list(found.values()) == [unknown]
    missing_description = {**unknown, "rule_id": "R-FUTURE-002"}
    del missing_description["description"]
    _findings(missing_description, found)
    assert list(found.values())[-1]["description"] == "R-FUTURE-002"


def test_deferred_history_keeps_observed_log_images(tmp_path, monkeypatch):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        evidence(runtime, tmp_path, case_id)
        tools(runtime, tmp_path, monkeypatch)
        assert finish(runtime, case_id)["complete"]
        view = call(runtime, "get_case_data", case_id=case_id)
        record = call(runtime, "get_history_page", case_id=case_id)["items"][0]["record"]
        detail = call(runtime, "get_analysis_detail", case_id=case_id, kind="history", identity=record["id"])["detail"]
        bundled = call(runtime, "get_history_page", case_id=case_id, include_details=True)
        single = call(runtime, "get_analysis_detail", case_id=case_id, kind="history", identity=record["id"], qualified_table=record["table"])
        assert bundled["items"][0]["detail"] == single["detail"]
        assert bundled["items"][0]["findings"] == single["findings"]
        assert detail["events"]
        assert detail["events"][0]["database"] == record["database"]
        assert "before" in detail["events"][0] and "after" in detail["events"][0]
        # Identical source positions belonging to another case must never leak.
        other = create(runtime)
        connection, _, _ = runtime.session(case_id)
        with connection:
            connection.execute("INSERT INTO cases(case_id,case_name,examiner,workspace_path,created_at) VALUES (?,?,?,?,?)", (other, 'Other', 'Test', '/tmp', 'now'))
            connection.execute("UPDATE evidence_files SET case_id=? WHERE case_id=?", (other, case_id))
        assert call(runtime, "get_history_page", case_id=case_id, include_details=True)["items"][0]["detail"]["events"] == []
    finally:
        runtime.close()


def test_case_preview_counts_are_field_level_and_arrays_are_omitted(tmp_path, monkeypatch):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        other = create(runtime, "Other")
        connection, stores, _ = runtime.session(case_id)
        result = run_pipeline(DS02)
        for stage in ("grouping", "correlation", "reconstruction", "reconciliation"):
            getattr(stores.domain, "save_" + stage)(case_id, getattr(result, stage))
        # Preview must not invoke the expensive full projection.
        monkeypatch.setattr("sidecar.desktop.case_view", lambda *args: (_ for _ in ()).throw(AssertionError("full projection")))
        preview = call(runtime, "get_case_preview", case_id=case_id)
        assert set(preview) == {"case", "evidence", "run", "pipeline"}
        metrics = preview["pipeline"]["metrics"]
        rows = encode(result.reconciliation)["rows"]
        assert metrics["exact"] == sum(row["result"] == "Exact" for row in rows)
        assert metrics["unresolved"] == sum(row["result"] == "Unresolved" for row in rows)
        assert metrics["records"] == len(result.correlation.records)
        assert metrics["transactions"] == len(result.grouping.transactions)
        assert '"histories"' not in json.dumps(preview)
        assert '"findings"' not in json.dumps(preview)
        assert '"tool_runs"' not in json.dumps(preview)
        empty = call(runtime, "get_case_preview", case_id=other)
        assert empty["evidence"] == []
        assert all(empty["pipeline"]["metrics"][key] is None for key in ("tables", "transactions", "records", "exact", "unresolved", "gaps"))
        runtime.auth.logout({})
        assert response(runtime, "get_case_preview", case_id=case_id)["error_code"] == "AuthenticationRequiredError"
    finally:
        runtime.close()


def test_preview_pipeline_and_evidence_match_full_view(tmp_path, monkeypatch):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        evidence(runtime, tmp_path, case_id)
        tools(runtime, tmp_path, monkeypatch)
        finish(runtime, case_id)
        view = call(runtime, "get_case_data", case_id=case_id)
        preview = call(runtime, "get_case_preview", case_id=case_id)
        assert preview["case"] == view["case"]
        assert preview["evidence"] == view["tables"]["evidence_files"]
        assert preview["run"] == view["run"]
        assert preview["pipeline"]["metrics"]["tables"] == len(view["tables"]["schemas"])
        assert preview["pipeline"]["summaries"]["extract_physical_rows"] == f"{view['table_counts']['physical_records']} rows"
        call(runtime, "save_case_notes", case_id=case_id, notes="Updated notes")
        assert call(runtime, "get_case_preview", case_id=case_id)["case"]["examiner_notes"] == "Updated notes"
    finally:
        runtime.close()
