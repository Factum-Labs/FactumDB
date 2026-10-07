"""Desktop requests must not serialize the full archival analysis trees."""
import json

from adapters.persistence._results import encode
from adapters.persistence.case_export import case_export
from tests.application.test_desktop_runtime import create, call, response, evidence, tools, finish
from sidecar.desktop import DesktopRuntime
from tests.fixtures.datasets import DS02
from tests.fixtures.pipeline import run_pipeline


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
        assert len(json.dumps(view)) < len(json.dumps(archive)) / 3
        assert "steps" not in view["analysis"]["reconstruction"]["histories"][0]
        assert "events" not in view["analysis"]["grouping"]["transactions"][0]
        assert "findings" not in view["analysis"]["reconciliation"]["rows"][0]
        history = result.reconstruction.histories[0]
        detail = call(runtime, "get_analysis_detail", case_id=case_id, kind="history", identity=history.record.id)
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


def test_deferred_history_keeps_observed_log_images(tmp_path, monkeypatch):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        evidence(runtime, tmp_path, case_id)
        tools(runtime, tmp_path, monkeypatch)
        assert finish(runtime, case_id)["complete"]
        view = call(runtime, "get_case_data", case_id=case_id)
        record = view["analysis"]["reconstruction"]["histories"][0]["record"]
        detail = call(runtime, "get_analysis_detail", case_id=case_id, kind="history", identity=record["id"])["detail"]
        assert detail["events"]
        assert detail["events"][0]["database"] == record["database"]
        assert "before" in detail["events"][0] and "after" in detail["events"][0]
    finally:
        runtime.close()
