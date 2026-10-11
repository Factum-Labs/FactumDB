"""Permanent deletion through the authenticated desktop command boundary."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.application.orchestration.models import StageAttempt, StageStatus
from tests.application.auth_support import authenticated_runtime
from tests.application.test_settings_management import call, send


@pytest.fixture
def runtime(tmp_path):
    value = authenticated_runtime(tmp_path / "workspace")
    yield value
    value.close()


def test_delete_removes_only_selected_case_and_preserves_original(runtime, tmp_path):
    case_id = call(runtime, "create_case", case_name="Delete me")["case_id"]
    other_id = call(runtime, "create_case", case_name="Keep me")["case_id"]
    original = tmp_path / "original.ibd"
    original.write_bytes(b"original evidence")
    call(runtime, "register_evidence", case_id=case_id, source_path=str(original))
    workspace = Path(runtime.cases.get(case_id).workspace_path)
    for directory in ("logs", "reports", "raw-output"):
        (workspace / directory / "sample.txt").write_text("case output")
    readonly = workspace / "working" / "readonly.ibd"
    readonly.write_bytes(b"working copy")
    readonly.chmod(0o444)
    assert call(runtime, "delete_case", case_id=case_id, confirmation="Delete me")["deleted"]
    assert not workspace.exists()
    assert original.read_bytes() == b"original evidence"
    assert case_id not in runtime.sessions
    assert runtime.cases.get(case_id) is None
    assert [row["id"] for row in call(runtime, "list_cases")] == [other_id]
    assert not send(runtime, "get_case_data", case_id=case_id)["ok"]


def test_delete_requires_confirmation_and_authenticated_session(runtime):
    case_id = call(runtime, "create_case", case_name="Private")["case_id"]
    for payload in (
        {"case_id": case_id},
        {"case_id": case_id, "confirmation": "Wrong"},
        {"case_id": "../outside", "confirmation": "Private"},
    ):
        assert not send(runtime, "delete_case", **payload)["ok"]
    call(runtime, "auth_lock")
    assert not send(runtime, "delete_case", case_id=case_id, confirmation="Private")["ok"]
    assert Path(runtime.cases.get(case_id).workspace_path).exists()


@pytest.mark.parametrize("replacement", ["root", "other", "outside"])
def test_delete_rejects_misdirected_workspace(runtime, tmp_path, replacement):
    case_id = call(runtime, "create_case", case_name="Case")["case_id"]
    other_id = call(runtime, "create_case", case_name="Other")["case_id"]
    case = runtime.cases.get(case_id)
    destinations = {
        "root": runtime.root / "cases",
        "other": Path(runtime.cases.get(other_id).workspace_path),
        "outside": tmp_path,
    }
    runtime.cases.save(replace(case, workspace_path=str(destinations[replacement])))
    assert not send(runtime, "delete_case", case_id=case_id, confirmation="Case")["ok"]
    assert Path(case.workspace_path).exists()
    assert destinations[replacement].exists()


def test_delete_rejects_original_evidence_inside_case_workspace(runtime):
    case_id = call(runtime, "create_case", case_name="Case")["case_id"]
    original = Path(runtime.cases.get(case_id).workspace_path) / "original.ibd"
    original.write_bytes(b"original evidence")
    call(runtime, "register_evidence", case_id=case_id, source_path=str(original))
    assert not send(runtime, "delete_case", case_id=case_id, confirmation="Case")["ok"]
    assert original.read_bytes() == b"original evidence"


def test_delete_rejects_running_analysis(runtime):
    case_id = call(runtime, "create_case", case_name="Case")["case_id"]
    result = call(runtime, "start_pipeline", case_id=case_id)
    repository = runtime.session(case_id)[2]
    run = repository.get(result["run_id"])
    stage = replace(run.stages[0], status=StageStatus.RUNNING, attempts=(
        StageAttempt(1, StageStatus.RUNNING, datetime.now(UTC)),
    ))
    repository.save(replace(run, stages=(stage, *run.stages[1:])))
    assert not send(runtime, "delete_case", case_id=case_id, confirmation="Case")["ok"]
    assert Path(runtime.cases.get(case_id).workspace_path).exists()


def test_delete_failure_keeps_catalog_entry(runtime, monkeypatch):
    case_id = call(runtime, "create_case", case_name="Case")["case_id"]
    def fail(*args, **kwargs):
        raise PermissionError("Case folder is in use")
    monkeypatch.setattr("sidecar.desktop.shutil.rmtree", fail)
    assert not send(runtime, "delete_case", case_id=case_id, confirmation="Case")["ok"]
    assert [case["id"] for case in call(runtime, "list_cases")] == [case_id]
