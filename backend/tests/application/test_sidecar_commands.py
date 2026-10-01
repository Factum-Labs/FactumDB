"""JSON-lines command tests using real use cases and the composed orchestrator."""

import io
import json
import unittest
from dataclasses import replace
from unittest.mock import Mock

from sidecar.commands import COMMAND_FIELDS, ApplicationServices
from sidecar.composition import build_application_services
from sidecar.main import build_router
from sidecar.protocol import serve
from tests.application import test_pipeline_composition as fixtures
from tests.application.fakes import FixedIds, MemoryWorkspaces, StaticInspector


class SidecarCommandTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PipelineCompositionTests()
        self.f.setUp()
        self.services = build_application_services(
            self.f.dependencies, self.f.adapters,
            workspaces=MemoryWorkspaces(), inspector=StaticInspector(),
        )
        self.router = build_router(self.services)

    def call(self, command, payload, router=None):
        output = io.StringIO()
        serve(io.StringIO(json.dumps({
            "request_id": "req-1", "command": command, "payload": payload,
        }) + "\n"), output, router or self.router)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        response = json.loads(lines[0])
        self.assertEqual(response["request_id"], "req-1")
        return response

    def test_create_register_verify_through_shared_dependencies(self):
        f = self.f
        f.dependencies.cases.items.clear()
        f.evidence.items.clear()
        dependencies = replace(f.dependencies, ids=FixedIds("case-1", "evidence-1", "run-1"))
        router = build_router(build_application_services(
            dependencies, f.adapters, workspaces=MemoryWorkspaces(), inspector=StaticInspector(),
        ))
        case = self.call("create_case", {"case_name": " Investigation ", "examiner": " Nisal "}, router)
        self.assertTrue(case["ok"], case)
        self.assertEqual(case["result"]["case_id"], "case-1")
        self.assertEqual(case["result"]["case_name"], "Investigation")
        self.assertEqual(case["result"]["examiner"], "Nisal")
        registered = self.call("register_evidence", {
            "case_id": "case-1", "source_path": "/source/accounts.ibd",
        }, router)
        self.assertTrue(registered["ok"], registered)
        self.assertFalse(registered["result"]["verified"])
        verified = self.call("verify_evidence", {
            "case_id": "case-1", "evidence_id": "evidence-1",
        }, router)
        self.assertTrue(verified["ok"], verified)
        self.assertTrue(verified["result"]["verified"])
        self.assertEqual(verified["result"]["verification_status"], "verified")
        started = self.call("start_pipeline", {"case_id": "case-1"}, router)
        self.assertEqual(started["result"]["run_id"], "run-1")

    def test_start_status_and_stage_execution_complete_pipeline(self):
        started = self.call("start_pipeline", {"case_id": "case-1"})
        self.assertTrue(started["ok"], started)
        self.assertTrue(all(s["status"] == "pending" for s in started["result"]["stages"]))
        before = self.f.pipelines.get("run-1")
        status = self.call("get_pipeline_status", {"run_id": "run-1"})
        self.assertIs(before, self.f.pipelines.get("run-1"))
        self.assertEqual(status["result"], started["result"])
        for _ in range(10):
            response = self.call("run_next_stage", {"run_id": "run-1"})
            self.assertTrue(response["ok"], response)
        self.assertTrue(response["result"]["complete"])
        self.assertIsNotNone(self.f.domain.reconciliation)
        self.assertIsInstance(response["result"]["stages"][0]["attempts"][0]["started_at"], str)

    def test_cancel_is_requested_then_applied_at_next_stage_boundary(self):
        self.call("start_pipeline", {"case_id": "case-1"})
        response = self.call("cancel_pipeline", {"run_id": "run-1"})
        self.assertTrue(response["result"]["cancel_requested"])
        self.assertFalse(response["result"]["stopped"])
        response = self.call("run_next_stage", {"run_id": "run-1"})
        self.assertTrue(response["result"]["stopped"])
        self.assertTrue(all(s["status"] == "cancelled" for s in response["result"]["stages"]))
        self.f.copies.create.assert_not_called()

    def test_failed_stage_and_retry_are_distinct_from_command_errors(self):
        self.f.schema.extract.side_effect = RuntimeError("tool failed")
        self.call("start_pipeline", {"case_id": "case-1"})
        for _ in range(3):
            response = self.call("run_next_stage", {"run_id": "run-1"})
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["stages"][2]["status"], "failed")
        self.f.schema.extract.side_effect = None
        retried = self.call("retry_pipeline", {"run_id": "run-1"})
        self.assertEqual(retried["result"]["stages"][2]["status"], "pending")
        self.assertEqual(len(retried["result"]["stages"][2]["attempts"]), 1)
        response = self.call("run_next_stage", {"run_id": "run-1"})
        self.assertEqual(response["result"]["stages"][2]["status"], "succeeded")

    def test_all_commands_reject_invalid_payloads_before_service_calls(self):
        mocks = [Mock() for _ in range(4)]
        router = build_router(ApplicationServices(
            create_case=mocks[0], register_evidence=mocks[1],
            verify_evidence=mocks[2], pipeline=mocks[3],
        ))
        for command, fields in COMMAND_FIELDS.items():
            valid = dict.fromkeys(fields, "value")
            for field in fields:
                for invalid in (None, "", " ", 1, True, [], {}):
                    with self.subTest(command=command, field=field, invalid=invalid):
                        response = self.call(command, {**valid, field: invalid}, router)
                        self.assertEqual(response["error_code"], "InvalidPayloadError")
                missing = {key: value for key, value in valid.items() if key != field}
                self.assertEqual(self.call(command, missing, router)["error_code"],
                                 "InvalidPayloadError")
            self.assertEqual(self.call(command, {**valid, "extra": "value"}, router)["error_code"],
                             "InvalidPayloadError")
        self.assertTrue(all(not service.mock_calls for service in mocks))

    def test_missing_run_and_case_return_application_errors(self):
        for command in ("get_pipeline_status", "run_next_stage", "cancel_pipeline", "retry_pipeline"):
            self.assertEqual(self.call(command, {"run_id": "missing"})["error_code"], "NotFoundError")
        self.assertEqual(self.call("start_pipeline", {"case_id": "missing"})["error_code"],
                         "NotFoundError")

    def test_conflict_and_retry_prerequisite_are_structured(self):
        self.call("start_pipeline", {"case_id": "case-1"})
        self.assertEqual(self.call("start_pipeline", {"case_id": "case-1"})["error_code"],
                         "ConflictError")
        self.assertEqual(self.call("retry_pipeline", {"run_id": "run-1"})["error_code"],
                         "PrerequisiteError")

    def test_unconfigured_router_exposes_commands_and_health(self):
        router = build_router()
        self.assertFalse(self.call("health", {}, router)["result"]["application_configured"])
        for command, fields in COMMAND_FIELDS.items():
            response = self.call(command, dict.fromkeys(fields, "value"), router)
            self.assertEqual(response["error_code"], "ApplicationNotConfiguredError")

    def test_invalid_payload_does_not_stop_subsequent_requests(self):
        output = io.StringIO()
        serve(io.StringIO(
            '{"request_id":"bad","command":"create_case","payload":{}}\n'
            '{"request_id":"good","command":"health","payload":{}}\n'
        ), output, self.router)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[0]["error_code"], "InvalidPayloadError")
        self.assertTrue(responses[1]["ok"])
