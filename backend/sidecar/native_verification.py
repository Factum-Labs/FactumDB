"""Private, request-scoped exchange with the native desktop host.

The renderer only sends auth_signup. This exchange is consumed on the sidecar's
inherited pipes while that request is running; it is not a router command.
"""

import hmac
import json
import secrets
from contextlib import contextmanager

from core.application.authentication import AuthenticationError


class NativeVerificationBridge:
    def __init__(self, input_stream, output_stream):
        self.input = input_stream
        self.output = output_stream
        self.request_id = None
        self.used = False

    @contextmanager
    def request_scope(self, request):
        self.request_id = request.request_id if request.command == "auth_signup" else None
        self.used = False
        try:
            yield
        finally:
            self.request_id = None
            self.used = True

    def verify(self):
        if self.request_id is None or self.used:
            raise AuthenticationError("Windows Hello verification requires the desktop app")
        self.used = True
        nonce = secrets.token_hex(32)
        challenge = {
            "kind": "device_verification_request",
            "request_id": self.request_id,
            "nonce": nonce,
        }
        try:
            self.output.write(json.dumps(challenge) + "\n")
            self.output.flush()
            response = json.loads(self.input.readline())
        except (OSError, ValueError) as error:
            raise AuthenticationError("Windows Hello verification bridge disconnected") from error
        fields = {"kind", "request_id", "nonce", "result", "message"}
        if (
            not isinstance(response, dict)
            or set(response) != fields
            or response["kind"] != "device_verification_response"
            or response["request_id"] != self.request_id
            or not isinstance(response["nonce"], str)
            or not response["nonce"].isascii()
            or not hmac.compare_digest(response["nonce"], nonce)
        ):
            raise AuthenticationError(
                "Windows Hello verification response did not match this sign-up"
            )
        if response["result"] != "verified" or response["message"] is not None:
            message = response["message"]
            if not isinstance(message, str) or not message:
                message = "Windows Hello verification cancelled or unavailable"
            raise AuthenticationError(message)
