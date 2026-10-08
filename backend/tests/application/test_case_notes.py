"""Examiner notes survive reopen and exports, independently of analysis."""
import json

from tests.application.auth_support import authenticated_runtime as DesktopRuntime
from tests.application.test_desktop_runtime import call, create, evidence, finish, response, tools


def test_notes_survive_analysis_export_and_restart(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    notes = "Acquired from imaged host FIN-DB-02.\nKeep original evidence untouched."
    with_runtime = DesktopRuntime(root)
    try:
        case_id = create(with_runtime)
        other_id = create(with_runtime, "Other case")
        call(with_runtime, "save_case_notes", case_id=case_id, notes=notes)
        evidence(with_runtime, tmp_path, case_id)
        tools(with_runtime, tmp_path, monkeypatch)
        assert finish(with_runtime, case_id)["complete"]
        assert call(with_runtime, "get_case_data", case_id=other_id)["case"]["examiner_notes"] == ""
        path = tmp_path / "report.json"
        call(with_runtime, "export_case", case_id=case_id, format="JSON", path=str(path))
        exported = json.loads(path.read_text(encoding="utf-8"))
        assert exported["tables"]["cases"][0]["examiner_notes"] == notes
    finally:
        with_runtime.close()
    reopened = DesktopRuntime(root)
    try:
        assert call(reopened, "get_case_data", case_id=case_id)["case"]["examiner_notes"] == notes
        assert not response(reopened, "save_case_notes", case_id=case_id, notes=123)["ok"]
        assert not response(reopened, "save_case_notes", case_id=case_id, notes="x", unexpected="x")["ok"]
        assert not response(reopened, "save_case_notes", case_id="missing", notes="x")["ok"]
        cleared = call(reopened, "save_case_notes", case_id=case_id, notes="")
        assert cleared["case"]["examiner_notes"] == ""
        assert cleared["run"]["complete"]
    finally:
        reopened.close()


def test_existing_cases_gain_empty_notes_without_losing_metadata(tmp_path):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        connection, _, _ = runtime.session(case_id)
        connection.execute("ALTER TABLE cases DROP COLUMN examiner_notes")
        connection.commit()
    finally:
        runtime.close()
    reopened = DesktopRuntime(tmp_path / "workspace")
    try:
        data = call(reopened, "get_case_data", case_id=case_id)
        assert data["case"]["case_name"] == "Case"
        assert data["case"]["examiner"] == "Examiner"
        assert data["case"]["examiner_notes"] == ""
        call(reopened, "save_case_notes", case_id=case_id, notes="Migrated case note")
    finally:
        reopened.close()
