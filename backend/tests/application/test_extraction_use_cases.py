from __future__ import annotations

import unittest

from core.application.errors import PrerequisiteError
from core.application.models import (
    Case,
    DecodedBinlog,
    EvidenceFile,
    EvidenceKind,
    EvidenceStageRequest,
    NormalizedEvidence,
    VerificationStatus,
)
from core.application.use_cases.extraction import (
    DecodeBinaryLogsUseCase,
    ExtractPhysicalRowsUseCase,
    ExtractSchemaUseCase,
    NormalizeEvidenceUseCase,
    RunPageValidationUseCase,
)
from tests.application.fakes import FIXED_NOW, FixedClock, MemoryCases, MemoryEvidence
from tests.fixtures.builders import accounts_schema, integrity, phys
from tests.fixtures.datasets import DS02, row


DIGEST = "a" * 64


def verified(kind: EvidenceKind, evidence_id: str = "evidence-1") -> EvidenceFile:
    filename = "accounts.ibd" if kind is EvidenceKind.IBD else "binlog.000018"
    return EvidenceFile(
        evidence_id,
        "case-1",
        f"/source/{filename}",
        filename,
        kind,
        42,
        DIGEST,
        FIXED_NOW,
        VerificationStatus.VERIFIED,
        f"/working/{filename}",
        DIGEST,
    )


class MemoryExtractionResults:
    def __init__(self) -> None:
        self.integrity = None
        self.schemas = None
        self.records = None
        self.decoded = None
        self.normalized = None

    def save_integrity(self, case_id: str, evidence_id: str, result: object) -> None:
        self.integrity = result

    def save_schemas(self, case_id: str, evidence_id: str, schemas: object) -> None:
        self.schemas = schemas

    def save_physical_records(self, case_id: str, evidence_id: str, records: object) -> None:
        self.records = records

    def save_decoded_binlog(self, case_id: str, evidence_id: str, decoded: object) -> None:
        self.decoded = decoded

    def save_normalized(self, case_id: str, normalized: object) -> None:
        self.normalized = normalized


class StaticAdapter:
    def __init__(self) -> None:
        self.integrity_result = integrity()
        self.schemas = (accounts_schema(),)
        self.records = (phys("accounts", row()),)
        self.decoded = DecodedBinlog(DS02.events, DS02.markers)

    def validate(self, working_copy_path: str):
        return self.integrity_result

    def extract(self, working_copy_path: str):
        if working_copy_path.endswith(".ibd"):
            return self.schemas
        return ()

    def decode(self, working_copy_path: str) -> DecodedBinlog:
        return self.decoded


class StaticRowExtractor:
    def __init__(self, records: tuple) -> None:
        self.records = records

    def extract(self, working_copy_path: str):
        return self.records


class StaticNormalizer:
    def __init__(self, normalized: NormalizedEvidence) -> None:
        self.normalized = normalized

    def normalize(self, case_id: str) -> NormalizedEvidence:
        return self.normalized


class ExtractionUseCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ibd = verified(EvidenceKind.IBD)
        self.binlog = verified(EvidenceKind.BINLOG, "evidence-2")
        self.evidence = MemoryEvidence(self.ibd, self.binlog)
        self.results = MemoryExtractionResults()
        self.adapter = StaticAdapter()

    def test_page_validation_persists_result(self) -> None:
        receipt = RunPageValidationUseCase(
            self.evidence, self.adapter, self.results, FixedClock()
        ).execute(EvidenceStageRequest("case-1", self.ibd.id))
        self.assertIs(self.results.integrity, self.adapter.integrity_result)
        self.assertEqual(receipt.operation, "page_validation")

    def test_schema_extraction_persists_schemas(self) -> None:
        receipt = ExtractSchemaUseCase(
            self.evidence, self.adapter, self.results, FixedClock()
        ).execute(EvidenceStageRequest("case-1", self.ibd.id))
        self.assertEqual(self.results.schemas, self.adapter.schemas)
        self.assertEqual(receipt.item_count, 1)

    def test_physical_row_extraction_persists_records(self) -> None:
        extractor = StaticRowExtractor(self.adapter.records)
        receipt = ExtractPhysicalRowsUseCase(
            self.evidence, extractor, self.results, FixedClock()
        ).execute(EvidenceStageRequest("case-1", self.ibd.id))
        self.assertEqual(self.results.records, self.adapter.records)
        self.assertEqual(receipt.item_count, 1)

    def test_binlog_decoding_persists_events_and_markers(self) -> None:
        receipt = DecodeBinaryLogsUseCase(
            self.evidence, self.adapter, self.results, FixedClock()
        ).execute(EvidenceStageRequest("case-1", self.binlog.id))
        self.assertIs(self.results.decoded, self.adapter.decoded)
        self.assertEqual(receipt.item_count, len(DS02.events) + len(DS02.markers))

    def test_extraction_rejects_wrong_evidence_kind(self) -> None:
        with self.assertRaisesRegex(PrerequisiteError, "expected ibd"):
            RunPageValidationUseCase(
                self.evidence, self.adapter, self.results, FixedClock()
            ).execute(EvidenceStageRequest("case-1", self.binlog.id))

    def test_extraction_rejects_unverified_evidence(self) -> None:
        unverified = EvidenceFile(
            "unverified",
            "case-1",
            "/source/other.ibd",
            "other.ibd",
            EvidenceKind.IBD,
            1,
            DIGEST,
            FIXED_NOW,
        )
        evidence = MemoryEvidence(unverified)
        with self.assertRaisesRegex(PrerequisiteError, "not verified"):
            ExtractSchemaUseCase(evidence, self.adapter, self.results, FixedClock()).execute(
                EvidenceStageRequest("case-1", unverified.id)
            )

    def test_normalization_persists_complete_bundle(self) -> None:
        normalized = NormalizedEvidence(
            DS02.schemas, DS02.physical, DS02.events, DS02.markers
        )
        receipt = NormalizeEvidenceUseCase(
            MemoryCases(
                Case(
                    "case-1",
                    "Investigation",
                    "Nisal",
                    FIXED_NOW,
                    "/workspaces/case-1",
                )
            ),
            StaticNormalizer(normalized),
            self.results,
            FixedClock(),
        ).execute("case-1")
        self.assertIs(self.results.normalized, normalized)
        self.assertGreater(receipt.item_count, 0)


if __name__ == "__main__":
    unittest.main()
