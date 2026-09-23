from __future__ import annotations

import unittest

from core.application.errors import ConflictError, EvidenceIntegrityError, NotFoundError
from core.application.models import (
    Case,
    CreateCaseRequest,
    EvidenceFile,
    EvidenceKind,
    RegisterEvidenceRequest,
    VerificationStatus,
    VerifyEvidenceRequest,
)
from core.application.use_cases.cases import CreateCaseUseCase
from core.application.use_cases.evidence import RegisterEvidenceUseCase, VerifyEvidenceUseCase
from tests.application.fakes import (
    FIXED_NOW,
    FixedClock,
    FixedIds,
    MappingHasher,
    MemoryCases,
    MemoryEvidence,
    MemoryWorkspaces,
    StaticInspector,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def a_case() -> Case:
    return Case("case-1", "Investigation", "Nisal", FIXED_NOW, "/workspaces/case-1")


def evidence_file() -> EvidenceFile:
    return EvidenceFile(
        "evidence-1",
        "case-1",
        "/source/accounts.ibd",
        "accounts.ibd",
        EvidenceKind.IBD,
        42,
        DIGEST_A,
        FIXED_NOW,
    )


class FakeCopies:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.discarded: list[str] = []

    def create(self, case: Case, evidence: EvidenceFile) -> str:
        path = f"{case.workspace_path}/working/{evidence.filename}"
        self.created.append(path)
        return path

    def discard(self, path: str) -> None:
        self.discarded.append(path)


class CreateCaseTests(unittest.TestCase):
    def test_creates_workspace_and_persists_trimmed_case(self) -> None:
        cases = MemoryCases()
        workspaces = MemoryWorkspaces()
        use_case = CreateCaseUseCase(cases, workspaces, FixedIds("case-1"), FixedClock())

        response = use_case.execute(CreateCaseRequest("  Investigation  ", " Nisal "))

        self.assertEqual(response.case.name, "Investigation")
        self.assertEqual(response.case.examiner, "Nisal")
        self.assertIs(cases.get("case-1"), response.case)
        self.assertEqual(workspaces.created, ["/workspaces/case-1"])

    def test_rejects_invalid_input_before_creating_workspace(self) -> None:
        workspaces = MemoryWorkspaces()
        use_case = CreateCaseUseCase(MemoryCases(), workspaces, FixedIds("case-1"), FixedClock())

        with self.assertRaisesRegex(ValueError, "case name"):
            use_case.execute(CreateCaseRequest("   ", "Nisal"))

        self.assertEqual(workspaces.created, [])

    def test_discards_workspace_when_persistence_fails(self) -> None:
        cases = MemoryCases()
        cases.fail_save = True
        workspaces = MemoryWorkspaces()
        use_case = CreateCaseUseCase(cases, workspaces, FixedIds("case-1"), FixedClock())

        with self.assertRaises(OSError):
            use_case.execute(CreateCaseRequest("Investigation", "Nisal"))

        self.assertEqual(workspaces.discarded, ["/workspaces/case-1"])


class RegisterEvidenceTests(unittest.TestCase):
    def test_registers_canonical_metadata_and_source_hash(self) -> None:
        cases = MemoryCases(a_case())
        evidence = MemoryEvidence()
        hasher = MappingHasher({"/source/accounts.ibd": DIGEST_A})
        use_case = RegisterEvidenceUseCase(
            cases,
            evidence,
            StaticInspector(),
            hasher,
            FixedIds("evidence-1"),
            FixedClock(),
        )

        response = use_case.execute(RegisterEvidenceRequest("case-1", "/source/accounts.ibd"))

        self.assertEqual(response.evidence.source_sha256, DIGEST_A)
        self.assertEqual(response.evidence.kind, EvidenceKind.IBD)
        self.assertIs(evidence.get("case-1", "evidence-1"), response.evidence)

    def test_rejects_unknown_case(self) -> None:
        use_case = RegisterEvidenceUseCase(
            MemoryCases(),
            MemoryEvidence(),
            StaticInspector(),
            MappingHasher({}),
            FixedIds("evidence-1"),
            FixedClock(),
        )
        with self.assertRaises(NotFoundError):
            use_case.execute(RegisterEvidenceRequest("missing", "/source/accounts.ibd"))

    def test_rejects_duplicate_source_in_same_case(self) -> None:
        use_case = RegisterEvidenceUseCase(
            MemoryCases(a_case()),
            MemoryEvidence(evidence_file()),
            StaticInspector(),
            MappingHasher({}),
            FixedIds("evidence-2"),
            FixedClock(),
        )
        with self.assertRaises(ConflictError):
            use_case.execute(RegisterEvidenceRequest("case-1", "/source/accounts.ibd"))


class VerifyEvidenceTests(unittest.TestCase):
    def test_verifies_matching_working_copy(self) -> None:
        evidence = MemoryEvidence(evidence_file())
        copies = FakeCopies()
        copy_path = "/workspaces/case-1/working/accounts.ibd"
        use_case = VerifyEvidenceUseCase(
            MemoryCases(a_case()), evidence, copies, MappingHasher({copy_path: DIGEST_A})
        )

        response = use_case.execute(VerifyEvidenceRequest("case-1", "evidence-1"))

        self.assertTrue(response.verified)
        self.assertEqual(response.evidence.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(response.evidence.working_copy_sha256, DIGEST_A)

    def test_persists_hash_mismatch_as_an_integrity_failure(self) -> None:
        evidence = MemoryEvidence(evidence_file())
        copies = FakeCopies()
        copy_path = "/workspaces/case-1/working/accounts.ibd"
        use_case = VerifyEvidenceUseCase(
            MemoryCases(a_case()), evidence, copies, MappingHasher({copy_path: DIGEST_B})
        )

        with self.assertRaises(EvidenceIntegrityError):
            use_case.execute(VerifyEvidenceRequest("case-1", "evidence-1"))

        saved = evidence.get("case-1", "evidence-1")
        assert saved is not None
        self.assertEqual(saved.verification_status, VerificationStatus.HASH_MISMATCH)
        self.assertEqual(copies.discarded, [])


if __name__ == "__main__":
    unittest.main()
