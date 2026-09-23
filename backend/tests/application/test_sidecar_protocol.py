from __future__ import annotations

import io
import json
import unittest

from sidecar.main import build_router
from sidecar.protocol import CommandRouter, SidecarRequest, serve


class SidecarProtocolTests(unittest.TestCase):
    def test_health_request_has_one_correlated_json_response(self) -> None:
        input_stream = io.StringIO(
            '{"request_id":"req-1","command":"health","payload":{}}\n'
        )
        output_stream = io.StringIO()
        serve(input_stream, output_stream, build_router())

        response = json.loads(output_stream.getvalue())
        self.assertEqual(response["request_id"], "req-1")
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["protocol"], 1)

    def test_invalid_request_does_not_terminate_following_requests(self) -> None:
        input_stream = io.StringIO(
            "not-json\n"
            '{"request_id":"req-2","command":"health","payload":{}}\n'
        )
        output_stream = io.StringIO()
        serve(input_stream, output_stream, build_router())

        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(responses[0]["error_code"], "invalid_request")
        self.assertTrue(responses[1]["ok"])

    def test_unknown_command_is_structured_failure(self) -> None:
        response = build_router().dispatch(SidecarRequest("req-1", "missing", {}))
        self.assertFalse(response.ok)
        self.assertEqual(response.error_code, "unknown_command")

    def test_handler_failure_is_returned_without_traceback(self) -> None:
        router = CommandRouter()

        def fail(payload: object) -> object:
            raise RuntimeError("adapter unavailable")

        router.register("fail", fail)
        response = router.dispatch(SidecarRequest("req-1", "fail", {}))
        self.assertEqual(response.error_code, "RuntimeError")
        self.assertEqual(response.error_message, "adapter unavailable")


if __name__ == "__main__":
    unittest.main()
