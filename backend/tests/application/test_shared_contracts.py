"""Regression checks for the merged model and port packages."""

import importlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from typing import get_type_hints

from core.application import models, ports
from core.application.models.create_case_models import CreateCaseRequest, CreateCaseResponse
from core.domain.models.case import Case
from core.domain.models.evidence import EvidenceFile, EvidenceKind, ToolRun, ToolRunStatus


class SharedContractTests(unittest.TestCase):
    def test_packages_expose_every_public_contract(self) -> None:
        for package in (models, ports):
            self.assertTrue(hasattr(package, "__path__"))
            for name in package.__all__:
                with self.subTest(package=package.__name__, name=name):
                    self.assertIsNotNone(getattr(package, name))

    def test_repository_and_application_models_are_identical(self) -> None:
        for model, workflow, repository, argument in (
            (Case, ports.CaseRepository, ports.CaseRepositoryPort, "case"),
            (EvidenceFile, ports.EvidenceRepository, ports.EvidenceRepositoryPort, "evidence"),
            (ToolRun, ports.ToolRunRepository, ports.ToolRunRepositoryPort, "run"),
        ):
            self.assertIs(getattr(models, model.__name__), model)
            self.assertIs(get_type_hints(workflow.save)[argument], model)
            self.assertIs(get_type_hints(repository.save)[argument], model)

    def test_case_request_and_response_have_one_definition(self) -> None:
        self.assertIs(models.CreateCaseRequest, CreateCaseRequest)
        self.assertIs(models.CreateCaseResponse, CreateCaseResponse)
        request = CreateCaseRequest(case_name="Investigation", examiner="Nisal")
        case = Case.create(
            request.case_name, request.examiner, case_id="case-1",
            created_at=datetime.now(timezone.utc), workspace_path="/workspace/case",
        )
        response = CreateCaseResponse(case)
        self.assertEqual(request.name, case.case_name)
        self.assertEqual(response.case_id, case.case_id)
        self.assertEqual(response.created_at, case.created_at.isoformat())

    def test_evidence_lifecycle_preserves_acquisition_metadata(self) -> None:
        evidence = EvidenceFile(
            id="evidence-1", case_id="case-1", source_path="/source/table.ibd",
            filename="table.ibd", kind=EvidenceKind.IBD, size_bytes=42,
            source_sha256="a" * 64, registered_at=datetime.now(timezone.utc),
            acquisition_method="FLUSH TABLES FOR EXPORT",
        )
        self.assertFalse(evidence.is_verified())
        verified = evidence.with_verification("/work/table.ibd", "a" * 64)
        self.assertTrue(verified.is_verified())
        self.assertEqual(verified.acquisition_method, evidence.acquisition_method)
        self.assertEqual(verified.evidence_id, evidence.id)
        self.assertEqual(verified.sha256_original, verified.sha256_working)
        self.assertFalse(evidence.with_verification("/work/table.ibd", "b" * 64).is_verified())

    def test_tool_run_preserves_structured_audit_data(self) -> None:
        now = datetime.now(timezone.utc)
        run = ToolRun(
            id="run-1", case_id="case-1", evidence_id="evidence-1", tool_name="ibd2sdi",
            tool_version="8", executable_path="/tools/ibd2sdi", executable_sha256="a" * 64,
            arguments=("/work/table.ibd",), started_at=now,
        )
        self.assertFalse(run.succeeded())
        completed = replace(run, status=ToolRunStatus.SUCCEEDED, finished_at=now, exit_code=0)
        self.assertTrue(completed.succeeded())
        self.assertEqual(completed.tool_run_id, run.id)
        self.assertEqual(completed.arguments, run.arguments)

    def test_existing_consumers_import_with_new_packages(self) -> None:
        for name in (
            "core.application.use_cases", "core.application.orchestration",
            "adapters.filesystem", "adapters.tools.ibd2sdi_adapter",
            "adapters.tools.ibd2sql_adapter", "adapters.tools.innochecksum_adapter",
            "adapters.tools.mysqlbinlog_adapter", "sidecar.main",
        ):
            with self.subTest(module=name):
                importlib.import_module(name)
