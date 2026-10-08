"""Dependency-free WSL/native Linux smoke checks. Run from the backend directory."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.security.linux import LinuxDeviceSecurity
from sidecar.desktop import DesktopRuntime
from sidecar.protocol import SidecarRequest
from tests.application.auth_support import PASSWORD, FakeDeviceSecurity


def call(runtime, command, **payload):
    return runtime.router().dispatch(SidecarRequest("smoke", command, payload))


with tempfile.TemporaryDirectory(prefix="factumdb-linux-auth-") as directory:
    runtime = DesktopRuntime(directory, device=FakeDeviceSecurity())
    try:
        assert call(runtime, "list_cases").error_code == "AuthenticationRequiredError"
        assert call(
            runtime,
            "auth_signup",
            username="Examiner",
            password=PASSWORD,
            password_confirmation=PASSWORD,
        ).ok
        created = call(runtime, "create_case", case_name="Linux test", examiner="Spoof")
        assert created.ok
        case_id = created.result["case_id"]
        assert (
            call(runtime, "get_case_data", case_id=case_id).result["case"]["examiner"] == "Examiner"
        )
        assert call(runtime, "auth_logout").ok
        assert (
            call(runtime, "get_case_data", case_id=case_id).error_code
            == "AuthenticationRequiredError"
        )
    finally:
        runtime.close()
    runtime = DesktopRuntime(directory, device=FakeDeviceSecurity())
    try:
        assert call(runtime, "auth_status").result["user"] is None
        assert call(runtime, "auth_login", username="EXAMINER", password=PASSWORD).ok
        assert call(runtime, "get_case_data", case_id=case_id).ok
        assert LinuxDeviceSecurity().identity().startswith("linux:uid:")
    finally:
        runtime.close()
    print(
        "PASS: Linux shared accounts, guarded access, examiner binding, logout and restart",
        flush=True,
    )

if "--expect-unavailable" in sys.argv:
    with tempfile.TemporaryDirectory(prefix="factumdb-linux-native-") as directory:
        runtime = DesktopRuntime(directory)
        try:
            result = call(
                runtime,
                "auth_signup",
                username="Native",
                password=PASSWORD,
                password_confirmation=PASSWORD,
            )
            assert not result.ok, "This environment unexpectedly allowed device verification"
            assert result.error_code == "AuthenticationError", result
            assert runtime.catalog.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            print(
                "PASS: native polkit refuses account creation without working device verification"
            )
            print(result.error_message)
        finally:
            runtime.close()
