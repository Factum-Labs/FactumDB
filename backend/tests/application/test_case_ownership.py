"""Owner isolation through real command routing, persistence and export adapters."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from adapters.persistence.sqlite_database import initialise
from sidecar.desktop import DesktopRuntime
from tests.application.auth_support import PASSWORD, FakeDeviceSecurity, authenticated_runtime
from tests.application.test_desktop_runtime import call, create, evidence, finish, response, tools


@pytest.fixture
def runtime(tmp_path):
    value = authenticated_runtime(tmp_path / "workspace")
    yield value
    value.close()


def switch(runtime, username):
    call(runtime, "auth_logout")
    if runtime.auth.accounts.find(username.lower()):
        call(runtime, "auth_login", username=username, password=PASSWORD)
    else:
        call(runtime, "auth_signup", username=username, password=PASSWORD,
             password_confirmation=PASSWORD)


def analysed(runtime, tmp_path, monkeypatch):
    case_id = create(runtime, "Private case")
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    run = finish(runtime, case_id)
    assert run["complete"]
    return case_id, run


def test_all_case_routes_deny_other_accounts_and_hide_their_cases(runtime, tmp_path, monkeypatch):
    case_id, run = analysed(runtime, tmp_path, monkeypatch)
    view = call(runtime, "get_case_data", case_id=case_id)
    tool_id = view["tables"]["tool_runs"][0]["tool_run_id"]
    evidence_id = view["tables"]["evidence_files"][0]["evidence_id"]
    preview = call(runtime, "preview_export", case_id=case_id, format="JSON")
    switch(runtime, "Reviewer")
    assert runtime.sessions == {} and runtime.export_preview is None
    own_id = create(runtime, "Reviewer case")
    assert [case["id"] for case in call(runtime, "list_cases")] == [own_id]
    assert set(runtime.sessions) == {own_id}
    blocked = [
        ("get_case_header", {"case_id": case_id}),
        ("get_screen_page", {"case_id": case_id, "kind": "transactions"}),
        ("get_screen_detail", {"case_id": case_id, "kind": "histories", "identity": "x"}),
        ("get_screen_context", {"case_id": case_id, "kind": "pipeline"}),
        ("get_screen_summary", {"case_id": case_id}),
        ("get_screen_coverage", {"case_id": case_id, "kind": "grouping"}),
        ("locate_screen_item", {"case_id": case_id, "kind": "transactions", "identity": "x"}),
        ("get_case_data", {"case_id": case_id}),
        ("get_analysis_detail", {"case_id": case_id, "kind": "history", "identity": "x"}),
        ("save_case_notes", {"case_id": case_id, "notes": "overwrite"}),
        ("delete_case", {"case_id": case_id, "confirmation": "Private case"}),
        ("register_evidence", {"case_id": case_id, "source_path": str(tmp_path / "accounts.ibd")}),
        ("verify_evidence", {"case_id": case_id, "evidence_id": evidence_id}),
        ("start_pipeline", {"case_id": case_id}),
        ("read_tool_output", {"case_id": case_id, "run_id": tool_id, "stream": "stdout"}),
        ("preview_export", {"case_id": case_id, "format": "JSON"}),
        ("export_case", {"case_id": case_id, "format": "JSON",
                         "path": str(tmp_path / "stolen.json")}),
        ("export_preview_page", {"preview_token": preview["preview_token"], "page": 1}),
    ]
    blocked += [(command, {"run_id": run["run_id"]}) for command in (
        "get_pipeline_status", "run_next_stage", "cancel_pipeline", "retry_pipeline",
    )]
    for command, payload in blocked:
        denied = response(runtime, command, **payload)
        assert not denied["ok"], command
        assert "Private case" not in json.dumps(denied)
    assert not (tmp_path / "stolen.json").exists()
    switch(runtime, "Examiner")
    assert call(runtime, "get_case_data", case_id=case_id)["case"]["case_name"] == "Private case"
    assert [case["id"] for case in call(runtime, "list_cases")] == [case_id]


def test_foreign_working_files_cannot_be_imported_or_used_as_export_destinations(
    runtime, tmp_path, monkeypatch,
):
    first, _ = analysed(runtime, tmp_path, monkeypatch)
    foreign_file = runtime.root / "cases" / first / "working" / "private.ibd"
    foreign_file.write_bytes(b"private evidence")
    switch(runtime, "Reviewer")
    second, _ = analysed(runtime, tmp_path, monkeypatch)
    assert not response(runtime, "register_evidence", case_id=second,
                        source_path=str(foreign_file))["ok"]
    destination = foreign_file.parent / "intrusion.json"
    assert not response(runtime, "export_case", case_id=second, format="JSON",
                        path=str(destination))["ok"]
    assert not destination.exists()


def test_exports_record_signed_in_actor_for_all_formats_and_survive_restart(
    runtime, tmp_path, monkeypatch,
):
    case_id, _ = analysed(runtime, tmp_path, monkeypatch)
    actor = runtime.auth.require_actor()
    for format in ("JSON", "PDF"):
        path = tmp_path / ("report." + format.lower())
        assert not response(runtime, "export_case", case_id=case_id, format=format,
                            path=str(path), actor_username="Spoof")["ok"]
        call(runtime, "export_case", case_id=case_id, format=format, path=str(path))
        record = runtime.session(case_id)[1].reports.latest(case_id, format.lower())
        assert record.actor_id == actor["actor_id"]
        assert record.actor_username == actor["actor_username"]
        assert record.version == 1 and record.created_at.tzinfo is not None
        for output in record.files:
            file = path
            assert output.sha256 == hashlib.sha256(file.read_bytes()).hexdigest()
    reopened = authenticated_runtime(runtime.root)
    try:
        history = call(reopened, "get_case_data", case_id=case_id)["tables"]["reports"]
        assert len(history) == 2
        assert all({key: report[key] for key in actor} == actor for report in history)
    finally:
        reopened.close()


def test_legacy_ownership_is_sealed_and_cannot_be_claimed_by_a_later_signup(runtime):
    case_id = create(runtime)
    unknown_id = "unknown-legacy"
    runtime.cases.save(replace(runtime.cases.get(case_id), id=unknown_id, examiner="FutureUser"))
    with runtime.catalog:
        runtime.catalog.execute("DROP TABLE case_owners")
    reopened = authenticated_runtime(runtime.root)
    try:
        assert call(reopened, "get_case_data", case_id=case_id)
        assert [case["id"] for case in call(reopened, "list_cases")] == [case_id]
        switch(reopened, "FutureUser")
        assert call(reopened, "list_cases") == []
        assert not response(reopened, "get_case_data", case_id=unknown_id)["ok"]
    finally:
        reopened.close()
    again = DesktopRuntime(runtime.root, device=FakeDeviceSecurity())
    try:
        call(again, "auth_login", username="FutureUser", password=PASSWORD)
        assert call(again, "list_cases") == []
    finally:
        again.close()


def test_report_actor_migration_preserves_unknown_history(runtime, tmp_path, monkeypatch):
    case_id, _ = analysed(runtime, tmp_path, monkeypatch)
    call(runtime, "export_case", case_id=case_id, format="JSON", path=str(tmp_path / "old.json"))
    connection, stores, _ = runtime.session(case_id)
    with connection:
        connection.execute("ALTER TABLE reports DROP COLUMN actor_id")
        connection.execute("ALTER TABLE reports DROP COLUMN actor_username")
    initialise(connection)
    old = stores.reports.latest(case_id, "json")
    assert old.actor_id is None and old.actor_username is None
    call(runtime, "export_case", case_id=case_id, format="JSON", path=str(tmp_path / "new.json"))
    new = stores.reports.latest(case_id, "json")
    assert new.version == 2 and new.actor_username == "Examiner"


def test_storage_and_workspace_operations_do_not_expose_other_users(runtime, tmp_path):
    first = create(runtime)
    (runtime.root / "cases" / first / "working" / "private.ibd").write_bytes(b"12345")
    backup = tmp_path / "examiner.fdbbackup"
    call(runtime, "backup_workspace", path=str(backup))
    switch(runtime, "Reviewer")
    second = create(runtime)
    (runtime.root / "cases" / second / "working" / "own.ibd").write_bytes(b"12")
    usage = call(runtime, "storage_usage")
    assert set(usage["cases"]) == {second}
    assert usage["categories"]["working"] == 2
    for command, payload in (
        ("backup_workspace", {"path": str(tmp_path / "stolen.fdbbackup")}),
        ("inspect_workspace_backup", {"path": str(backup)}),
        ("restore_workspace", {"path": str(backup), "sha256": "x", "current_password": PASSWORD}),
        ("get_workspace_folder", {}),
    ):
        assert response(runtime, command, **payload)["error_code"] == "PermissionError"
    assert not (tmp_path / "stolen.fdbbackup").exists()


def test_other_account_backup_is_rejected_even_in_single_account_workspace(runtime, tmp_path):
    create(runtime)
    backup = tmp_path / "examiner.fdbbackup"
    call(runtime, "backup_workspace", path=str(backup))
    other = DesktopRuntime(tmp_path / "other", device=FakeDeviceSecurity())
    try:
        call(other, "auth_signup", username="Reviewer", password=PASSWORD,
             password_confirmation=PASSWORD)
        denied = response(other, "inspect_workspace_backup", path=str(backup))
        assert denied["error_code"] == "PermissionError"
        assert not response(other, "restore_workspace", path=str(backup),
                            sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
                            current_password=PASSWORD)["ok"]
        assert other.auth.require_user()["username"] == "Reviewer"
    finally:
        other.close()


def test_raw_output_is_separate_verified_and_owner_only(runtime, tmp_path, monkeypatch):
    case_id, _ = analysed(runtime, tmp_path, monkeypatch)
    tool = call(runtime, "get_case_data", case_id=case_id)["tables"]["tool_runs"][0]
    options = {"case_id": case_id, "run_id": tool["tool_run_id"], "stream": "stdout"}
    preview = call(runtime, "read_tool_output", **options)
    assert preview["sha256"] == tool["stdout_sha256"]
    path = Path(preview["path"])
    assert path.is_relative_to(runtime.root / "cases" / case_id / "raw-output")
    path.write_bytes(b"tampered")
    assert response(runtime, "read_tool_output", **options)["error_code"] == "ConflictError"
    switch(runtime, "Reviewer")
    assert response(runtime, "read_tool_output", **options)["error_code"] == "NotFoundError"
