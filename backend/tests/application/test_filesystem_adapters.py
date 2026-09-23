from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from adapters.filesystem import (
    FilesystemCaseWorkspace,
    FilesystemEvidenceInspector,
    FilesystemRawOutputStore,
    FilesystemWorkingCopyManager,
    Sha256FileHasher,
)
from core.application.models import (
    CompleteToolRunRequest,
    CreateCaseRequest,
    EvidenceKind,
    RegisterEvidenceRequest,
    StartToolRunRequest,
    VerifyEvidenceRequest,
)
from core.application.use_cases.audit import ToolRunAuditService
from core.application.use_cases.cases import CreateCaseUseCase
from core.application.use_cases.evidence import RegisterEvidenceUseCase, VerifyEvidenceUseCase
from tests.application.fakes import FixedClock, FixedIds, MemoryCases, MemoryEvidence


class FilesystemAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "workspaces"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workspace_creates_controlled_layout_and_discards_case_only(self) -> None:
        adapter = FilesystemCaseWorkspace(self.root)
        workspace = Path(adapter.create("case-1"))

        self.assertEqual(
            {entry.name for entry in workspace.iterdir()},
            {"working", "raw-output", "reports", "logs"},
        )
        adapter.discard(str(workspace))
        self.assertFalse(workspace.exists())
        self.assertTrue(self.root.exists())

    def test_workspace_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe case id"):
            FilesystemCaseWorkspace(self.root).create("../outside")

    def test_inspector_classifies_supported_evidence(self) -> None:
        inspector = FilesystemEvidenceInspector()
        expected = {
            "accounts.ibd": EvidenceKind.IBD,
            "mysql-bin.index": EvidenceKind.BINLOG_INDEX,
            "mysql-bin.000001": EvidenceKind.BINLOG,
            "binlog.000018": EvidenceKind.BINLOG,
        }
        for filename, kind in expected.items():
            with self.subTest(filename=filename):
                path = Path(self.temporary.name) / filename
                path.write_bytes(b"evidence")
                self.assertEqual(inspector.inspect(str(path)).kind, kind)

    def test_streaming_hasher_returns_expected_digest(self) -> None:
        source = Path(self.temporary.name) / "accounts.ibd"
        source.write_bytes(b"FactumDB evidence" * 100)
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(Sha256FileHasher(chunk_size=7).sha256(str(source)), expected)

    def test_real_adapters_complete_case_register_and_verify_flow(self) -> None:
        cases = MemoryCases()
        evidence = MemoryEvidence()
        workspace_adapter = FilesystemCaseWorkspace(self.root)
        case = CreateCaseUseCase(
            cases, workspace_adapter, FixedIds("case-1"), FixedClock()
        ).execute(CreateCaseRequest("Investigation", "Nisal")).case
        source = Path(self.temporary.name) / "accounts.ibd"
        source.write_bytes(b"forensic bytes")

        registered = RegisterEvidenceUseCase(
            cases,
            evidence,
            FilesystemEvidenceInspector(),
            Sha256FileHasher(),
            FixedIds("evidence-1"),
            FixedClock(),
        ).execute(RegisterEvidenceRequest(case.id, str(source))).evidence
        response = VerifyEvidenceUseCase(
            cases,
            evidence,
            FilesystemWorkingCopyManager(self.root),
            Sha256FileHasher(),
        ).execute(VerifyEvidenceRequest(case.id, registered.id))

        self.assertTrue(response.verified)
        copied = Path(response.evidence.verified_working_path or "")
        self.assertEqual(copied.read_bytes(), source.read_bytes())
        self.assertNotEqual(copied, source)

    def test_working_copy_refuses_to_overwrite_existing_copy(self) -> None:
        cases = MemoryCases()
        evidence = MemoryEvidence()
        case = CreateCaseUseCase(
            cases,
            FilesystemCaseWorkspace(self.root),
            FixedIds("case-1"),
            FixedClock(),
        ).execute(CreateCaseRequest("Investigation", "Nisal")).case
        source = Path(self.temporary.name) / "accounts.ibd"
        source.write_bytes(b"data")
        registered = RegisterEvidenceUseCase(
            cases,
            evidence,
            FilesystemEvidenceInspector(),
            Sha256FileHasher(),
            FixedIds("evidence-1"),
            FixedClock(),
        ).execute(RegisterEvidenceRequest(case.id, str(source))).evidence
        copies = FilesystemWorkingCopyManager(self.root)
        copies.create(case, registered)
        with self.assertRaises(FileExistsError):
            copies.create(case, registered)

    def test_raw_output_is_preserved_with_digest_and_no_overwrite(self) -> None:
        cases = MemoryCases()
        case = CreateCaseUseCase(
            cases,
            FilesystemCaseWorkspace(self.root),
            FixedIds("case-1"),
            FixedClock(),
        ).execute(CreateCaseRequest("Investigation", "Nisal")).case
        store = FilesystemRawOutputStore(self.root)
        content = b"exact utility output\x00\xff"

        reference = store.save(case, "run-1", "stdout", content)

        self.assertEqual(Path(reference.path).read_bytes(), content)
        self.assertEqual(reference.sha256, hashlib.sha256(content).hexdigest())
        with self.assertRaises(FileExistsError):
            store.save(case, "run-1", "stdout", b"replacement")

    def test_tool_run_audit_records_executable_arguments_and_raw_outputs(self) -> None:
        cases = MemoryCases()
        evidence_repository = MemoryEvidence()
        workspace = FilesystemCaseWorkspace(self.root)
        case = CreateCaseUseCase(
            cases, workspace, FixedIds("case-1"), FixedClock()
        ).execute(CreateCaseRequest("Investigation", "Nisal")).case
        source = Path(self.temporary.name) / "accounts.ibd"
        source.write_bytes(b"evidence")
        registered = RegisterEvidenceUseCase(
            cases,
            evidence_repository,
            FilesystemEvidenceInspector(),
            Sha256FileHasher(),
            FixedIds("evidence-1"),
            FixedClock(),
        ).execute(RegisterEvidenceRequest(case.id, str(source))).evidence
        verified = VerifyEvidenceUseCase(
            cases,
            evidence_repository,
            FilesystemWorkingCopyManager(self.root),
            Sha256FileHasher(),
        ).execute(VerifyEvidenceRequest(case.id, registered.id)).evidence
        executable = Path(self.temporary.name) / "innochecksum"
        executable.write_bytes(b"tool binary")
        runs = MemoryToolRuns()
        audit = ToolRunAuditService(
            cases,
            evidence_repository,
            runs,
            FilesystemRawOutputStore(self.root),
            Sha256FileHasher(),
            FixedIds("run-1"),
            FixedClock(),
        )

        running = audit.start(
            StartToolRunRequest(
                case.id,
                registered.id,
                "innochecksum",
                "8.4.0",
                str(executable),
                ("--page-type-summary", verified.verified_working_path or ""),
            )
        )
        completed = audit.complete(
            CompleteToolRunRequest(running.id, 0, b"valid pages", b"")
        )

        self.assertEqual(completed.arguments[0], "--page-type-summary")
        self.assertEqual(completed.exit_code, 0)
        assert completed.stdout is not None
        self.assertEqual(Path(completed.stdout.path).read_bytes(), b"valid pages")


class MemoryToolRuns:
    def __init__(self) -> None:
        self.items = {}

    def save(self, run) -> None:
        self.items[run.id] = run

    def get(self, run_id: str):
        return self.items.get(run_id)


if __name__ == "__main__":
    unittest.main()
