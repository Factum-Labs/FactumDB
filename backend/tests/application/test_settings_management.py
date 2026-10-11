"""Settings security, presentation and complete workspace recovery through JSON commands."""

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from adapters.filesystem.workspace_backup import inspect_backup
from core.application.preferences import DEFAULTS, display_time, report_times
from sidecar.desktop import DesktopRuntime
from sidecar.protocol import SidecarRequest
from tests.application.auth_support import PASSWORD, FakeDeviceSecurity, authenticated_runtime


def send(runtime, command, **payload):
    return json.loads(
        runtime.router().dispatch(SidecarRequest("settings-test", command, payload)).to_json()
    )


def call(runtime, command, **payload):
    response = send(runtime, command, **payload)
    assert response["ok"], response
    return response["result"]


@pytest.fixture
def runtime(tmp_path):
    runtime = authenticated_runtime(tmp_path / "workspace")
    yield runtime
    runtime.close()


def test_password_requires_current_password_confirmation_and_device(runtime):
    new = "New secure password 456"
    payload = {
        "current_password": "wrong password",
        "new_password": new,
        "password_confirmation": new,
    }
    assert not send(runtime, "change_password", **payload)["ok"]
    payload["current_password"] = PASSWORD
    payload["password_confirmation"] = "different password"
    assert not send(runtime, "change_password", **payload)["ok"]
    payload["password_confirmation"] = new
    assert call(runtime, "change_password", **payload)["changed"]
    call(runtime, "auth_logout")
    assert not send(runtime, "auth_login", username="Examiner", password=PASSWORD)["ok"]
    assert (
        call(runtime, "auth_login", username="Examiner", password=new)["user"]["username"]
        == "Examiner"
    )


def test_failed_unlocks_are_throttled_and_do_not_reveal_case_data(runtime):
    case_id = call(runtime, "create_case", case_name="Private case")["case_id"]
    call(runtime, "auth_lock")
    for _ in range(5):
        assert not send(runtime, "auth_unlock", password="incorrect")["ok"]
    assert "Too many" in send(runtime, "auth_unlock", password=PASSWORD)["error_message"]
    assert (
        send(runtime, "get_case_data", case_id=case_id)["error_code"]
        == "AuthenticationRequiredError"
    )
    assert send(runtime, "storage_usage")["error_code"] == "AuthenticationRequiredError"
    assert call(runtime, "auth_status")["locked"] is True


def test_idle_lock_is_enforced_by_backend_and_correct_unlock_preserves_session(runtime):
    call(runtime, "configure_preferences", **{**DEFAULTS, "lock_minutes": 1})
    runtime.auth.last_activity -= 61
    assert send(runtime, "get_settings")["error_code"] == "AuthenticationRequiredError"
    assert not send(runtime, "auth_touch")["ok"]  # Activity cannot unlock an expired session.
    call(runtime, "auth_unlock", password=PASSWORD)
    assert call(runtime, "get_settings")["preferences"]["lock_minutes"] == 1
    call(runtime, "configure_preferences", **{**DEFAULTS, "lock_minutes": 0})
    runtime.auth.last_activity -= 100000
    assert call(runtime, "get_settings")


def test_profile_and_preferences_persist_per_account_without_rewriting_history(runtime):
    case_id = call(runtime, "create_case", case_name="Historical case")["case_id"]
    profile = {"display_name": "Dr Examiner", "organization": "Lab", "examiner_id": "EX-17"}
    call(runtime, "configure_profile", **profile)
    prefs = {**DEFAULTS, "time_mode": "custom", "utc_offset_minutes": 330, "lock_minutes": 5}
    call(runtime, "configure_preferences", **prefs)
    assert call(runtime, "get_case_data", case_id=case_id)["case"]["examiner"] == "Examiner"
    call(runtime, "auth_logout")
    call(
        runtime, "auth_signup", username="Second", password=PASSWORD, password_confirmation=PASSWORD
    )
    assert call(runtime, "get_settings")["profile"] == {}
    assert call(runtime, "get_settings")["preferences"] == DEFAULTS
    assert runtime.auth.lock_minutes == DEFAULTS["lock_minutes"]
    restarted = DesktopRuntime(runtime.root, device=FakeDeviceSecurity())
    try:
        call(restarted, "auth_login", username="Examiner", password=PASSWORD)
        assert call(restarted, "get_settings")["profile"] == profile
        assert call(restarted, "get_settings")["preferences"] == prefs
        assert restarted.auth.lock_minutes == 5
    finally:
        restarted.close()


@pytest.mark.parametrize(
    "update",
    [
        {"lock_minutes": -1},
        {"time_mode": "invalid"},
        {"utc_offset_minutes": 841},
    ],
)
def test_invalid_preferences_leave_saved_settings_unchanged(runtime, update):
    assert not send(runtime, "configure_preferences", **{**DEFAULTS, **update})["ok"]
    assert call(runtime, "get_settings")["preferences"] == DEFAULTS


def test_time_presentation_preserves_original_and_unknown_timezone_values():
    preferences = {**DEFAULTS, "time_mode": "custom", "utc_offset_minutes": 330}
    original = "2026-10-11T23:30:00+00:00"
    tables = {"transactions": [{"commit_timestamp": original}]}
    assert display_time(original, preferences) == "2026-10-12T05:00:00+05:30"
    assert report_times(tables, preferences)["transactions"][0]["display"].endswith("+05:30")
    assert tables["transactions"][0]["commit_timestamp"] == original
    assert display_time("2026-10-11T23:30:00", preferences) == "2026-10-11T23:30:00"


def test_reopening_catalog_prunes_obsolete_preferences(runtime):
    saved = {**DEFAULTS, "obsolete_setting": True}
    runtime.auth.accounts.save_details("examiner", preferences=saved)
    reopened = DesktopRuntime(runtime.root, device=FakeDeviceSecurity())
    try:
        call(reopened, "auth_login", username="Examiner", password=PASSWORD)
        assert call(reopened, "get_settings")["preferences"] == DEFAULTS
        persisted = json.loads(
            reopened.catalog.execute(
                "SELECT preferences_json FROM users WHERE username_key = 'examiner'"
            ).fetchone()[0]
        )
        assert persisted == DEFAULTS
    finally:
        reopened.close()


def backup(runtime, tmp_path):
    destination = tmp_path / "workspace.fdbbackup"
    call(runtime, "backup_workspace", path=str(destination))
    return destination


def test_backup_snapshots_wal_data_and_restore_keeps_rollback_and_requires_login(runtime, tmp_path):
    case_id = call(runtime, "create_case", case_name="Before backup")["case_id"]
    working = runtime.root / "cases" / case_id / "working" / "verified.ibd"
    working.write_bytes(b"verified evidence bytes")
    call(runtime, "configure_profile", display_name="Before", organization="Lab", examiner_id="E1")
    destination = backup(runtime, tmp_path)
    manifest = inspect_backup(destination)
    assert f"cases/{case_id}/case.db" in manifest["files"]
    assert not any(name.endswith(("-wal", "-shm")) for name in manifest["files"])
    call(runtime, "create_case", case_name="After backup")
    call(runtime, "configure_profile", display_name="After", organization="Lab", examiner_id="E1")
    preview = call(runtime, "inspect_workspace_backup", path=str(destination))
    # Keep the same router alive: auth handlers must use the newly opened catalog.
    router = runtime.router()
    payload = {"path": str(destination), "sha256": preview["sha256"], "current_password": PASSWORD}
    response = router.dispatch(SidecarRequest("restore", "restore_workspace", payload))
    assert response.ok, response.error_message
    rollback = Path(response.result["rollback_path"])
    assert rollback.is_dir()
    assert working.read_bytes() == b"verified evidence bytes"
    assert (
        router.dispatch(SidecarRequest("locked", "list_cases", {})).error_code
        == "AuthenticationRequiredError"
    )
    assert router.dispatch(
        SidecarRequest("login", "auth_login", {"username": "Examiner", "password": PASSWORD})
    ).ok
    assert len(call(runtime, "list_cases")) == 1
    assert call(runtime, "get_settings")["profile"]["display_name"] == "Before"
    with sqlite3.connect(rollback / "catalog.db") as old:
        assert old.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2


def test_restore_into_different_workspace_rebases_operational_paths(runtime, tmp_path):
    case_id = call(runtime, "create_case", case_name="Portable")["case_id"]
    destination = backup(runtime, tmp_path)
    other = authenticated_runtime(tmp_path / "other-workspace")
    try:
        preview = call(other, "inspect_workspace_backup", path=str(destination))
        call(
            other,
            "restore_workspace",
            path=str(destination),
            sha256=preview["sha256"],
            current_password=PASSWORD,
        )
        call(other, "auth_login", username="Examiner", password=PASSWORD)
        case = call(other, "get_case_data", case_id=case_id)["case"]
        assert case["workspace_path"] == str(other.root / "cases" / case_id)
    finally:
        other.close()


def rewrite_archive(destination, change):
    with zipfile.ZipFile(destination) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    change(contents)
    with zipfile.ZipFile(destination, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def test_corrupt_and_traversal_backups_cannot_change_live_workspace(runtime, tmp_path):
    case_id = call(runtime, "create_case", case_name="Keep me")["case_id"]
    destination = backup(runtime, tmp_path)
    rewrite_archive(destination, lambda contents: contents.update({"catalog.db": b"corrupt"}))
    assert not send(runtime, "inspect_workspace_backup", path=str(destination))["ok"]
    assert call(runtime, "get_case_data", case_id=case_id)["case"]["case_name"] == "Keep me"

    def traversal(contents):
        manifest = json.loads(contents["manifest.json"])
        contents["../escape.txt"] = b"unsafe"
        manifest["files"]["../escape.txt"] = {
            "size": 6,
            "sha256": hashlib.sha256(b"unsafe").hexdigest(),
        }
        contents["manifest.json"] = json.dumps(manifest).encode()

    rewrite_archive(destination, traversal)
    assert not send(runtime, "inspect_workspace_backup", path=str(destination))["ok"]
    assert not (tmp_path / "escape.txt").exists()


def test_restore_requires_password_and_preview_digest(runtime, tmp_path):
    destination = backup(runtime, tmp_path)
    preview = call(runtime, "inspect_workspace_backup", path=str(destination))
    assert not send(
        runtime,
        "restore_workspace",
        path=str(destination),
        sha256=preview["sha256"],
        current_password="wrong",
    )["ok"]
    assert not send(
        runtime,
        "restore_workspace",
        path=str(destination),
        sha256="stale",
        current_password=PASSWORD,
    )["ok"]
    assert call(runtime, "get_settings")


def test_usage_and_backup_destinations(runtime, tmp_path):
    case_id = call(runtime, "create_case", case_name="Size")["case_id"]
    working = runtime.root / "cases" / case_id / "working" / "sample.ibd"
    working.write_bytes(b"1234567890")
    usage = call(runtime, "storage_usage")
    assert usage["categories"]["working"] == 10
    assert usage["cases"][case_id] >= 10
    assert usage["total_bytes"] == sum(usage["categories"].values())
    assert usage["free_bytes"] > 0
    assert not send(runtime, "backup_workspace", path=str(runtime.root / "bad.fdbbackup"))["ok"]
    destination = backup(runtime, tmp_path)
    assert not send(runtime, "backup_workspace", path=str(destination))["ok"]


def test_activation_failure_rolls_back_workspace_and_closes_restored_catalog(runtime, tmp_path):
    case_id = call(runtime, "create_case", case_name="Original workspace")["case_id"]
    destination = backup(runtime, tmp_path)

    def invalid_settings(contents):
        # A self-consistent archive with invalid settings passes checksum validation
        # but must still restore the original workspace if initialization rejects it.
        contents["settings.json"] = b"invalid JSON"
        manifest = json.loads(contents["manifest.json"])
        manifest["files"]["settings.json"] = {
            "size": len(contents["settings.json"]),
            "sha256": hashlib.sha256(contents["settings.json"]).hexdigest(),
        }
        contents["manifest.json"] = json.dumps(manifest).encode()

    rewrite_archive(destination, invalid_settings)
    preview = call(runtime, "inspect_workspace_backup", path=str(destination))
    response = send(
        runtime,
        "restore_workspace",
        path=str(destination),
        sha256=preview["sha256"],
        current_password=PASSWORD,
    )
    assert not response["ok"]
    assert response["error_code"] == "JSONDecodeError"
    assert (
        call(runtime, "get_case_data", case_id=case_id)["case"]["case_name"] == "Original workspace"
    )
    assert not (runtime.root / "settings.json").exists()
