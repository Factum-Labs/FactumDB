"""Private approval must be fresh and bound to an active sign-up request."""

import io
import json

import pytest

from core.application.authentication import AuthenticationError
from sidecar.desktop import DesktopRuntime
from sidecar.native_verification import NativeVerificationBridge
from sidecar.protocol import SidecarRequest, serve
from tests.application.auth_support import PASSWORD, FakeDeviceSecurity

NONCE = "ab" * 32


def reply(**overrides):
    return {
        "kind": "device_verification_response",
        "request_id": "signup-1",
        "nonce": NONCE,
        "result": "verified",
        "message": None,
        **overrides,
    }


def request(command="auth_signup", request_id="signup-1", **overrides):
    payload = (
        {
            "username": "Examiner",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
            **overrides,
        }
        if command == "auth_signup"
        else {}
    )
    return SidecarRequest(request_id, command, payload)


def wire(request):
    return (
        json.dumps(
            {
                "request_id": request.request_id,
                "command": request.command,
                "payload": request.payload,
            }
        )
        + "\n"
    )


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr("sidecar.native_verification.secrets.token_hex", lambda length: NONCE)
    return NativeVerificationBridge(io.StringIO(json.dumps(reply()) + "\n"), io.StringIO())


def test_bridge_accepts_one_correlated_approval(bridge):
    with bridge.request_scope(request()):
        bridge.verify()
        with pytest.raises(AuthenticationError):
            bridge.verify()
    with pytest.raises(AuthenticationError):
        bridge.verify()
    challenge = json.loads(bridge.output.getvalue())
    assert challenge == {
        "kind": "device_verification_request",
        "request_id": "signup-1",
        "nonce": NONCE,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_id": "another-request"},
        {"nonce": "cd" * 32},
        {"nonce": 123},
        {"nonce": "é" * 64},
        {"kind": "auth_signup"},
        {"result": True},
        {"result": "denied", "message": "Windows Hello cancelled"},
        {"result": "unavailable"},
        {"message": "untrusted approval"},
        {"approved": True},
    ],
)
def test_bridge_rejects_mismatches_denials_and_forged_flags(bridge, overrides):
    bridge.input = io.StringIO(json.dumps(reply(**overrides)) + "\n")
    with bridge.request_scope(request()), pytest.raises(AuthenticationError):
        bridge.verify()


@pytest.mark.parametrize("line", ["", "not-json\n", "[]\n", "true\n"])
def test_bridge_disconnect_or_malformed_response_fails_closed(bridge, line):
    bridge.input = io.StringIO(line)
    with bridge.request_scope(request()), pytest.raises(AuthenticationError):
        bridge.verify()


def test_bridge_only_works_inside_signup_scope(bridge):
    with bridge.request_scope(request("health")), pytest.raises(AuthenticationError):
        bridge.verify()
    assert bridge.output.getvalue() == ""


def runtime_with_bridge(tmp_path, bridge):
    class BridgeDevice(FakeDeviceSecurity):
        def verify(self):
            bridge.verify()
            return self.identity()

    return DesktopRuntime(tmp_path, device=BridgeDevice())


def test_real_signup_consumes_private_reply_and_returns_only_public_status(tmp_path, bridge):
    runtime = runtime_with_bridge(tmp_path, bridge)
    bridge.input = io.StringIO(
        wire(request()) + json.dumps(reply()) + "\n" + wire(request("health", "health-2"))
    )
    try:
        serve(bridge.input, bridge.output, runtime.router(), native_verification=bridge)
        lines = [json.loads(line) for line in bridge.output.getvalue().splitlines()]
        assert len(lines) == 3
        assert lines[0]["kind"] == "device_verification_request"
        assert lines[1]["result"] == {"user": {"username": "Examiner"}}
        assert lines[2]["request_id"] == "health-2" and lines[2]["ok"]
        assert runtime.auth.accounts.find("examiner") is not None
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "change", [{"password_confirmation": "mismatch"}, {"device_verified": True}]
)
def test_bad_signup_does_not_request_native_prompt(tmp_path, bridge, change):
    runtime = runtime_with_bridge(tmp_path, bridge)
    try:
        with bridge.request_scope(request(**change)):
            result = runtime.router().dispatch(request(**change))
        assert not result.ok
        assert bridge.output.getvalue() == ""
        assert runtime.auth.accounts.find("examiner") is None
    finally:
        runtime.close()


def test_duplicate_registration_never_requests_native_prompt(tmp_path, bridge):
    runtime = runtime_with_bridge(tmp_path, bridge)
    try:
        with bridge.request_scope(request()):
            assert runtime.router().dispatch(request()).ok
        runtime.auth.logout({})
        before = bridge.output.getvalue()
        with bridge.request_scope(request(request_id="signup-2")):
            assert not runtime.router().dispatch(request(request_id="signup-2")).ok
        assert bridge.output.getvalue() == before
    finally:
        runtime.close()


def test_replayed_response_and_public_private_reply_command_cannot_register(
    tmp_path, bridge, monkeypatch
):
    runtime = runtime_with_bridge(tmp_path, bridge)
    nonces = iter([NONCE, "cd" * 32])
    monkeypatch.setattr(
        "sidecar.native_verification.secrets.token_hex", lambda length: next(nonces)
    )
    try:
        with bridge.request_scope(request()):
            assert runtime.router().dispatch(request()).ok
        runtime.auth.logout({})
        bridge.input = io.StringIO(json.dumps(reply(request_id="signup-2")) + "\n")
        second = request(request_id="signup-2", username="Another")
        with bridge.request_scope(second):
            assert runtime.router().dispatch(second).error_code == "AuthenticationError"
        assert runtime.auth.accounts.find("another") is None
        forged = SidecarRequest("forged", "device_verification_response", reply())
        assert runtime.router().dispatch(forged).error_code == "unknown_command"
    finally:
        runtime.close()
