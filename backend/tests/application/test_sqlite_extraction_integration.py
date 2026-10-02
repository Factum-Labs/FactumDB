"""SQLite extraction facade and provenance integration tests."""

import unittest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from core.application.errors import ConflictError, PrerequisiteError
from core.application.models import (
    Case, DecodedBinlog, EvidenceFile, EvidenceKind, NormalizedEvidence, ToolRun, ToolRunStatus,
    VerificationStatus,
)
from core.domain.models.canonical import AnalysisWarning
from tests.application.fakes import FIXED_NOW
from tests.fixtures.builders import integrity
from tests.fixtures.datasets import DS02


DIGEST = "a" * 64


class SqliteExtractionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.connection = open_case_database(":memory:")
        self.stores = build_sqlite_application_stores(self.connection, now=lambda: FIXED_NOW)
        self.stores.cases.save(Case("case-1", "Case", "Nisal", FIXED_NOW, "/case-1"))
        self.ibd = self._evidence("ibd-1", EvidenceKind.IBD, "accounts.ibd")
        self.binlog = self._evidence("log-1", EvidenceKind.BINLOG, "binlog.000018")
        self.stores.evidence.save(self.ibd)
        self.stores.evidence.save(self.binlog)

    def tearDown(self):
        self.connection.close()

    def _evidence(self, evidence_id, kind, filename):
        return EvidenceFile(
            evidence_id, "case-1", f"/source/{filename}", filename, kind, 1,
            DIGEST, FIXED_NOW, VerificationStatus.VERIFIED,
            f"/working/{filename}", DIGEST,
        )

    def _run(self, run_id, evidence_id, tool_name="innochecksum", status=ToolRunStatus.SUCCEEDED):
        run = ToolRun(
            run_id, "case-1", evidence_id, tool_name, "unknown", f"/bin/{tool_name}",
            DIGEST, (), FIXED_NOW, status, FIXED_NOW if status is not ToolRunStatus.RUNNING else None,
            0 if status is ToolRunStatus.SUCCEEDED else (1 if status is ToolRunStatus.FAILED else None),
        )
        self.stores.tool_runs.save(run)
        return run

    def test_saves_integrity_with_validated_provenance(self):
        run = self._run("run-1", self.ibd.id)
        self.stores.extraction.save_integrity("case-1", self.ibd.id, run.id, integrity())
        row = self.connection.execute(
            "SELECT tool_run_id FROM integrity_results WHERE evidence_id = ?", (self.ibd.id,)
        ).fetchone()
        self.assertEqual(row["tool_run_id"], run.id)

    def test_rejects_failed_or_mismatched_tool_run(self):
        # innochecksum is the exception: it exits 1 when it finds damage, so
        # its failed runs are accepted for integrity results.
        failed = self._run("failed", self.ibd.id, "ibd2sdi", status=ToolRunStatus.FAILED)
        with self.assertRaises(PrerequisiteError):
            self.stores.extraction.save_schemas("case-1", self.ibd.id, failed.id, ())
        other = self._run("other", self.binlog.id, "mysqlbinlog")
        with self.assertRaises(ConflictError):
            self.stores.extraction.save_integrity("case-1", self.ibd.id, other.id, integrity())

    def test_decoded_bundle_rolls_back_if_warning_save_fails(self):
        run = self._run("run-log", self.binlog.id, "mysqlbinlog")

        class FailingWarnings:
            def save_many(self, *args):
                raise OSError("warning store unavailable")

        self.stores.extraction._warnings = FailingWarnings()
        decoded = DecodedBinlog(
            DS02.events, DS02.markers,
            (AnalysisWarning("TEST_WARNING", "test warning", {}),),
        )
        with self.assertRaises(OSError):
            self.stores.extraction.save_decoded_binlog(
                "case-1", self.binlog.id, run.id, decoded,
            )
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM binlog_events").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)

    def test_normalized_storage_records_the_normalization(self):
        self.stores.extraction.save_normalized("case-1", NormalizedEvidence((), (), (), ()))
        row = self.connection.execute(
            "SELECT case_id FROM normalizations WHERE case_id = 'case-1'"
        ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
