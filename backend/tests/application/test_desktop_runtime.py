"""Desktop contract through real services, SQLite, copies and tool parsers.

External tool execution is mocked; its recorded output and provenance are real.
"""
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.application.orchestration.models import StageAttempt, StageStatus
from tests.application.auth_support import authenticated_runtime as DesktopRuntime
from sidecar.protocol import SidecarRequest
from sidecar.views import _present
from tests.application.test_tool_integration import BINLOG, ROWS, SDI

_sdi = json.loads(SDI)
_sdi[0]["object"]["dd_object"]["mysql_version_id"] = 80411
SDI = json.dumps(_sdi).encode()


@pytest.fixture
def runtime(tmp_path):
    value = DesktopRuntime(tmp_path / "workspace")
    yield value
    value.close()


def response(runtime, command, **payload):
    # Include the actual transport serialization boundary.
    return json.loads(runtime.router().dispatch(SidecarRequest("test", command, payload)).to_json())


def call(runtime, command, **payload):
    result = response(runtime, command, **payload)
    assert result["ok"], result
    return result["result"]


def create(runtime, name="Case"):
    return call(runtime, "create_case", case_name=name, examiner="Examiner")["case_id"]


def evidence(runtime, tmp_path, case_id):
    ibd = tmp_path / "accounts.ibd"
    log = tmp_path / "binlog.000001"
    ibd.write_bytes(b"tablespace test input")
    log.write_bytes(b"binary log test input")
    for path in (ibd, log):
        call(runtime, "register_evidence", case_id=case_id, source_path=str(path))
    return ibd, log


def tools(runtime, tmp_path, monkeypatch, fail=False):
    config = dict(runtime.settings)
    for name in ("innochecksum", "ibd2sdi", "mysqlbinlog"):
        path = tmp_path / (name + ".exe")
        path.write_bytes(b"test tool executable")
        config[name + "_path"] = str(path)
    script = tmp_path / "main.py"
    script.write_text("# test ibd2sql", encoding="utf-8")
    config.update(ibd2sql_path=str(script), python_path=sys.executable)
    call(runtime, "configure_settings", **config)

    def execute(command, **kwargs):
        name = Path(command[0]).stem
        code, stdout, stderr = 0, b"", b""
        if "--version" in command:
            stdout = b"test-tool Ver 8.4.11"
        elif name == "innochecksum":
            if fail:
                code, stderr = 1, b"Error: validation failed"
            elif "-S" in command:
                stdout = b"1\tIndex page\n0\tUndo log page\n"
        elif name == "ibd2sdi":
            stdout = SDI
        elif name.startswith("python"):
            stdout = ROWS
        elif name == "mysqlbinlog":
            stdout = BINLOG
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, code, stdout, stderr)
    monkeypatch.setattr(subprocess, "run", execute)


def finish(runtime, case_id):
    run = call(runtime, "start_pipeline", case_id=case_id)
    while not run["stopped"]:
        run = call(runtime, "run_next_stage", run_id=run["run_id"])
    return run


def test_full_analysis_restart_provenance_export_and_case_isolation(runtime, tmp_path, monkeypatch):
    first = create(runtime)
    second = create(runtime, "Independent")
    evidence(runtime, tmp_path, first)
    tools(runtime, tmp_path, monkeypatch)
    run = finish(runtime, first)
    assert run["complete"], [s for s in run["stages"] if s["status"] == "failed"]
    data = call(runtime, "get_case_data", case_id=first)
    assert set(data["analysis"]) == {"grouping", "correlation", "reconstruction", "reconciliation"}
    assert data["analysis"]["reconciliation"]["rows"]
    assert data["table_counts"]["physical_records"] == 1
    assert data["tables"]["physical_records"] == []
    assert len(data["tables"]["tool_runs"]) == 5
    assert all(row["verification_status"] == "verified" for row in data["tables"]["evidence_files"])
    for row in data["tables"]["evidence_files"]:
        # The store order is by id; compare by source path instead.
        assert Path(row["working_copy_path"]).read_bytes() == Path(row["source_path"]).read_bytes()
    other = call(runtime, "get_case_data", case_id=second)
    assert other["tables"]["evidence_files"] == []
    assert other["analysis"] == {}

    tool = next(t for t in data["tables"]["tool_runs"] if t["tool_name"] == "ibd2sql")
    output = call(runtime, "read_tool_output", case_id=first, run_id=tool["tool_run_id"], stream="stdout")
    assert output["text"] == ROWS.decode()
    assert response(runtime, "read_tool_output", case_id=second, run_id=tool["tool_run_id"], stream="stdout")["error_code"] == "NotFoundError"
    for format, name in (("JSON", "case.json"), ("CSV", "csv")):
        destination = tmp_path / name
        call(runtime, "export_case", case_id=first, format=format, path=str(destination))
        assert destination.exists()
        assert not response(runtime, "export_case", case_id=first, format=format, path=str(destination))["ok"]
    exported = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert "users" not in exported["tables"]
    assert "auth_throttle" not in exported["tables"]
    assert exported["tables"]["analysis_results"]
    assert exported["tables"]["pipeline_runs"][0]["run"]["stages"][-1]["status"] == "succeeded"
    assert (tmp_path / "csv" / "reconciliation.csv").exists()

    reopened = DesktopRuntime(runtime.root)
    try:
        restored = call(reopened, "get_case_data", case_id=first)
        assert restored["run"]["complete"]
        assert restored["analysis"] == data["analysis"]
        assert len(call(reopened, "list_cases")) == 2
        assert call(reopened, "get_settings")["tools"] == runtime.settings
    finally:
        reopened.close()


def test_errors_cancellation_retry_and_new_evidence_invalidation(runtime, tmp_path, monkeypatch):
    case_id = create(runtime)
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch, fail=True)
    failed = finish(runtime, case_id)
    assert failed["stages"][1]["status"] == "failed"
    assert not failed["complete"]
    assert not response(runtime, "export_case", case_id=case_id, format="JSON", path=str(tmp_path / "bad.json"))["ok"]
    tools(runtime, tmp_path, monkeypatch)
    retried = call(runtime, "retry_pipeline", run_id=failed["run_id"])
    assert retried["stages"][1]["status"] == "pending"
    extra = tmp_path / "more.ibd"
    extra.write_bytes(b"more")
    blocked = response(runtime, "register_evidence", case_id=case_id, source_path=str(extra))
    assert not blocked["ok"] and blocked["error_code"] == "ConflictError"
    while not retried["stopped"]:
        retried = call(runtime, "run_next_stage", run_id=retried["run_id"])
    assert retried["complete"], [s for s in retried["stages"] if s["status"] == "failed"]
    call(runtime, "register_evidence", case_id=case_id, source_path=str(extra))
    updated = call(runtime, "get_case_data", case_id=case_id)
    assert updated["run"] is None
    assert updated["analysis"] == {}
    assert not response(runtime, "run_next_stage", run_id=retried["run_id"])["ok"]
    run = call(runtime, "start_pipeline", case_id=case_id)
    call(runtime, "cancel_pipeline", run_id=run["run_id"])
    cancelled = call(runtime, "run_next_stage", run_id=run["run_id"])
    assert cancelled["stopped"]
    assert all(s["status"] == "cancelled" for s in cancelled["stages"])


def test_recovery_marks_interrupted_attempt_failed(runtime):
    case_id = create(runtime)
    run = call(runtime, "start_pipeline", case_id=case_id)
    connection, _, repository = runtime.session(case_id)
    model = repository.get(run["run_id"])
    attempt = StageAttempt(1, StageStatus.RUNNING, datetime.now(timezone.utc))
    stage = replace(model.stages[1], status=StageStatus.RUNNING, attempts=(attempt,))
    repository.save(replace(model, stages=(model.stages[0], stage, *model.stages[2:])))
    from adapters.persistence.sqlite_pipeline_repository import SqlitePipelineRepository
    recovered = SqlitePipelineRepository(connection).get(model.id)
    assert recovered.stages[1].status is StageStatus.FAILED
    assert recovered.stages[1].attempts[0].error_code == "InterruptedError"


def test_nested_errors_preserve_request_correlation(runtime):
    case_id = create(runtime)
    result = response(runtime, "verify_evidence", case_id=case_id, evidence_id="missing")
    assert not result["ok"]
    assert result["request_id"] == "test"
    assert result["error_code"] == "NotFoundError"


def test_evidence_and_tool_actors_follow_sessions_and_survive_restart(runtime, tmp_path, monkeypatch):
    from tests.application.auth_support import PASSWORD

    case_id = create(runtime)
    registrar = runtime.auth.require_actor()
    source = tmp_path / "actors.ibd"
    source.write_bytes(b"test evidence")
    assert not response(runtime, "register_evidence", case_id=case_id, source_path=str(source),
                        actor_id="forged", actor_username="Forged")["ok"]
    registered = call(runtime, "register_evidence", case_id=case_id, source_path=str(source))
    assert {key: registered[key] for key in registrar} == registrar
    call(runtime, "auth_logout")
    call(runtime, "auth_signup", username="Reviewer", password=PASSWORD,
         password_confirmation=PASSWORD)
    analyst = runtime.auth.require_actor()
    assert analyst["actor_id"] != registrar["actor_id"]
    verified = call(runtime, "verify_evidence", case_id=case_id,
                    evidence_id=registered["evidence_id"])
    assert {key: verified[key] for key in registrar} == registrar
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    view = call(runtime, "get_case_data", case_id=case_id)
    assert view["tables"]["tool_runs"]
    assert all({key: tool[key] for key in analyst} == analyst
               for tool in view["tables"]["tool_runs"])
    path = tmp_path / "actors.json"
    call(runtime, "export_case", case_id=case_id, format="JSON", path=str(path))
    exported = json.loads(path.read_text(encoding="utf-8"))["tables"]
    assert exported["evidence_files"][0]["actor_username"] == "Examiner"
    assert all(tool["actor_username"] == "Reviewer" for tool in exported["tool_runs"])
    reopened = DesktopRuntime(runtime.root)
    try:
        assert reopened.auth.require_actor() == registrar
        assert call(reopened, "get_case_data", case_id=case_id)["tables"]["tool_runs"] == view["tables"]["tool_runs"]
    finally:
        reopened.close()


def test_actor_column_migration_leaves_old_records_unknown(runtime, tmp_path, monkeypatch):
    from adapters.persistence.sqlite_database import initialise

    case_id = create(runtime)
    source = tmp_path / "legacy.ibd"
    source.write_bytes(b"legacy evidence")
    registered = call(runtime, "register_evidence", case_id=case_id, source_path=str(source))
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    connection, stores, _ = runtime.session(case_id)
    # Simulate the schema before actor fields existed, without changing its evidence.
    for table in ("evidence_files", "tool_runs"):
        for column in ("actor_id", "actor_username"):
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    initialise(connection)
    item = stores.evidence.get(case_id, registered["evidence_id"])
    assert item.actor_id is None and item.actor_username is None
    assert all(run.actor_id is None and run.actor_username is None
               for run in stores.tool_runs.list_by_evidence(item.id))
    assert item.source_sha256 == registered["source_sha256"]


def test_javascript_projection_keeps_large_integer_exact():
    assert _present({"values": [9007199254740993, None, 42]}) == {
        "values": [{"__integer__": "9007199254740993"}, None, 42]
    }


def test_bundle_defaults_follow_installation_and_preserve_custom_overrides(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "settings.json").write_text(json.dumps({
        "innochecksum_path": "innochecksum", "ibd2sdi_path": "ibd2sdi",
        "ibd2sql_path": "", "mysqlbinlog_path": "mysqlbinlog",
        "python_path": sys.executable, "include_deleted": True,
    }))
    def install(name):
        bundle = tmp_path / name
        bundle.mkdir()
        tools = {}
        for key in ("innochecksum", "ibd2sdi", "ibd2sql", "mysqlbinlog", "python"):
            relative = key + ".exe"
            (bundle / relative).write_bytes(b"bundle fixture")
            tools[key + "_path"] = relative
        (bundle / "manifest.json").write_text(json.dumps({"tools": tools}))
        monkeypatch.setenv("FACTUMDB_BUNDLE_ROOT", str(bundle))
        return bundle
    first = install("first install")
    runtime = DesktopRuntime(workspace)
    assert runtime.settings["python_path"] == str(first / "python.exe")
    assert runtime.settings["include_deleted"] is True
    custom = str(tmp_path / "custom mysqlbinlog.exe")
    runtime.configure({**runtime.settings, "mysqlbinlog_path": custom})
    runtime.close()
    saved = json.loads((workspace / "settings.json").read_text())["overrides"]
    assert "python_path" not in saved
    second = install("second install")
    runtime = DesktopRuntime(workspace)
    try:
        assert runtime.settings["python_path"] == str(second / "python.exe")
        assert runtime.settings["mysqlbinlog_path"] == custom
        runtime.configure({**runtime.settings, **runtime.bundled_tools})
        assert runtime.settings["mysqlbinlog_path"] == str(second / "mysqlbinlog.exe")
    finally:
        runtime.close()
