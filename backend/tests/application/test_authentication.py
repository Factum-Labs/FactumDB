"""Authentication boundaries through desktop JSON commands and real SQLite."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.application.authentication import AuthenticationError
from sidecar.desktop import DesktopRuntime
from sidecar.protocol import SidecarRequest
from tests.application.auth_support import PASSWORD, FakeDeviceSecurity


def send(runtime, command, **payload):
    return json.loads(
        runtime.router().dispatch(SidecarRequest("auth-test", command, payload)).to_json()
    )


def signup(runtime, username="Examiner"):
    return send(
        runtime, "auth_signup", username=username, password=PASSWORD, password_confirmation=PASSWORD
    )


@pytest.fixture
def runtime(tmp_path):
    instance = DesktopRuntime(tmp_path, device=FakeDeviceSecurity())
    yield instance
    instance.close()


@pytest.mark.parametrize(
    "command,payload",
    [
        ("list_cases", {}),
        ("get_settings", {}),
        ("create_case", {"case_name": "Test", "examiner": "Spoof"}),
        ("get_case_data", {"case_id": "anything"}),
        ("get_analysis_detail", {}),
        ("register_evidence", {}),
        ("verify_evidence", {}),
        ("start_pipeline", {}),
        ("run_next_stage", {}),
        ("get_pipeline_status", {}),
        ("cancel_pipeline", {}),
        ("retry_pipeline", {}),
        ("configure_settings", {}),
        ("export_case", {}),
        ("read_tool_output", {}),
        ("save_case_notes", {}),
    ],
)
def test_every_desktop_operation_requires_authentication(runtime, command, payload):
    assert send(runtime, command, **payload)["error_code"] == "AuthenticationRequiredError"


def test_signup_login_restart_logout_and_examiner_cannot_be_spoofed(runtime):
    assert send(runtime, "auth_status")["result"] == {"user": None}
    assert "workspace" not in send(runtime, "health")["result"]
    assert signup(runtime)["result"] == {"user": {"username": "Examiner"}}
    created = send(runtime, "create_case", case_name="Protected", examiner="Impersonated")["result"]
    case_id = created["case_id"]
    view = send(runtime, "get_case_data", case_id=case_id)["result"]
    assert view["case"]["examiner"] == "Examiner"
    assert "users" not in view["tables"]
    row = runtime.auth.accounts.find("examiner")
    assert row["salt"] and row["password_hash"] != PASSWORD.encode()
    assert PASSWORD not in json.dumps(dict(row), default=str)
    assert send(runtime, "auth_logout")["result"] == {"user": None}
    assert (
        send(runtime, "get_case_data", case_id=case_id)["error_code"]
        == "AuthenticationRequiredError"
    )
    assert not send(runtime, "auth_login", username="Examiner", password="wrong password 123")["ok"]
    assert send(runtime, "auth_login", username="EXAMINER", password=PASSWORD)["ok"]
    reopened = DesktopRuntime(runtime.root, device=FakeDeviceSecurity())
    try:
        assert send(reopened, "auth_status")["result"]["user"] is None
        assert send(reopened, "auth_login", username="Examiner", password=PASSWORD)["ok"]
        assert send(reopened, "get_case_data", case_id=case_id)["ok"]
    finally:
        reopened.close()


def test_existing_examiner_fields_follow_session_and_preserve_history(runtime):
    from adapters.persistence.case_export import case_export

    assert signup(runtime)["ok"]
    first = send(runtime, "create_case", case_name="First")["result"]["case_id"]
    assert send(runtime, "auth_logout")["ok"]
    assert signup(runtime, "Reviewer")["ok"]
    second = send(
        runtime, "create_case", case_name="Second", examiner="Impersonated"
    )["result"]["case_id"]
    for case_id, username in ((first, "Examiner"), (second, "Reviewer")):
        view = send(runtime, "get_case_data", case_id=case_id)["result"]
        assert view["case"]["examiner"] == username
        connection, _, _ = runtime.session(case_id)
        assert case_export(connection, case_id)["tables"]["cases"][0]["examiner"] == username
    cases = send(runtime, "list_cases")["result"]
    assert {case["id"]: case["examiner"] for case in cases} == {
        first: "Examiner", second: "Reviewer"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "xx", "password": PASSWORD, "password_confirmation": PASSWORD},
        {"username": "Examiner", "password": "short", "password_confirmation": "short"},
        {"username": "Examiner", "password": PASSWORD, "password_confirmation": "different"},
        {
            "username": "Examiner",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
            "device_verified": True,
        },
    ],
)
def test_invalid_signup_never_calls_device(runtime, payload):
    def unexpected():
        pytest.fail("Device prompt should not run for invalid inputs")

    runtime.auth.device.verify = unexpected
    assert not send(runtime, "auth_signup", **payload)["ok"]
    assert runtime.catalog.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_cancellation_and_different_os_user_cannot_register(runtime):
    def cancelled():
        raise AuthenticationError("Cancelled")

    runtime.auth.device.verify = cancelled
    assert signup(runtime)["error_code"] == "AuthenticationError"
    runtime.auth.device.verify = lambda: "another-device-user"
    assert not signup(runtime)["ok"]
    assert runtime.catalog.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_duplicate_names_device_binding_and_persisted_throttle(runtime, monkeypatch):
    assert signup(runtime)["ok"]
    send(runtime, "auth_logout")
    assert not signup(runtime, "EXAMINER")["ok"]
    monkeypatch.setattr("core.application.authentication.time.time", lambda: 1000)
    for _ in range(5):
        assert not send(runtime, "auth_login", username="Examiner", password="incorrect password")[
            "ok"
        ]
    reopened = DesktopRuntime(runtime.root, device=FakeDeviceSecurity())
    try:
        assert (
            "Too many attempts"
            in send(reopened, "auth_login", username="Examiner", password=PASSWORD)["error_message"]
        )
        monkeypatch.setattr("core.application.authentication.time.time", lambda: 1031)
        reopened.auth.device.identity = lambda: "another-device-user"
        assert not send(reopened, "auth_login", username="Examiner", password=PASSWORD)["ok"]
        reopened.auth.device.identity = lambda: "test:device-user"
        assert send(reopened, "auth_login", username="Examiner", password=PASSWORD)["ok"]
    finally:
        reopened.close()


def test_password_whitespace_is_preserved(runtime):
    password = "  spaced password  "
    assert send(
        runtime,
        "auth_signup",
        username="Whitespace",
        password=password,
        password_confirmation=password,
    )["ok"]
    send(runtime, "auth_logout")
    assert not send(runtime, "auth_login", username="Whitespace", password=password.strip())["ok"]
    assert send(runtime, "auth_login", username="Whitespace", password=password)["ok"]


@pytest.mark.parametrize("code", [1, 2, 3, 126, 127])
def test_linux_device_denials_fail_closed(monkeypatch, code):
    from adapters.security.linux import LinuxDeviceSecurity

    monkeypatch.setattr("adapters.security.linux.shutil.which", lambda name: "/usr/bin/pkcheck")
    monkeypatch.setattr("adapters.security.linux.os.getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: "1 (process name) " + " ".join(["0"] * 19 + ["123"]),
    )
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], code)
    )
    with pytest.raises(AuthenticationError):
        LinuxDeviceSecurity().verify()


def test_linux_device_uses_bound_process_and_interactive_polkit(monkeypatch):
    from adapters.security.linux import LinuxDeviceSecurity

    monkeypatch.setattr("adapters.security.linux.shutil.which", lambda name: "/usr/bin/pkcheck")
    monkeypatch.setattr("adapters.security.linux.os.getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: "1 (process name) " + " ".join(["0"] * 19 + ["123"]),
    )

    def run(command, **kwargs):
        assert command == [
            "/usr/bin/pkcheck",
            "--action-id",
            "org.factumdb.signup",
            "--process",
            f"{os.getpid()},123,1000",
            "--allow-user-interaction",
        ]
        assert kwargs["timeout"] == 120
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert LinuxDeviceSecurity().verify() == "linux:uid:1000"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native API")
def test_windows_can_identify_current_device_account_without_prompt():
    from adapters.security.windows import WindowsDeviceSecurity

    assert WindowsDeviceSecurity().identity().startswith("windows:sid:S-1-")


def test_linux_missing_verifier_and_timeout_fail_closed(monkeypatch):
    from adapters.security.linux import LinuxDeviceSecurity

    monkeypatch.setattr("adapters.security.linux.shutil.which", lambda name: None)
    with pytest.raises(AuthenticationError):
        LinuxDeviceSecurity().verify()
    monkeypatch.setattr("adapters.security.linux.shutil.which", lambda name: "/usr/bin/pkcheck")
    monkeypatch.setattr("adapters.security.linux.os.getuid", lambda: 1000, raising=False)
    stat = "1 (process name) " + " ".join(["0"] * 19 + ["123"])
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: stat)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("pkcheck", 120)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(AuthenticationError):
        LinuxDeviceSecurity().verify()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native API")
@pytest.mark.parametrize("approved", [False, True])
def test_windows_delegates_to_native_host_and_only_then_identifies_user(monkeypatch, approved):
    from adapters.security.windows import WindowsDeviceSecurity

    calls = []

    def verify():
        calls.append("verify")
        if not approved:
            raise AuthenticationError("Windows Hello cancelled")

    device = WindowsDeviceSecurity(verify_device=verify)

    def identity():
        calls.append("identity")
        return "current-user"

    monkeypatch.setattr(device, "identity", identity)
    if approved:
        assert device.verify() == "current-user"
        assert calls == ["verify", "identity"]
    else:
        with pytest.raises(AuthenticationError):
            device.verify()
        assert calls == ["verify"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native API")
def test_windows_standalone_signup_requires_native_bridge(tmp_path):
    runtime = DesktopRuntime(tmp_path)
    try:
        result = signup(runtime)
        assert result["error_code"] == "AuthenticationError"
        assert "desktop app" in result["error_message"]
        assert runtime.catalog.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    finally:
        runtime.close()
