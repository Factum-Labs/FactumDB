"""Use cases through real utility parsers, with only subprocess execution mocked."""

import json
import subprocess
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from adapters.tools import (
    Ibd2SdiAdapter,
    Ibd2SdiSchemaExtractor,
    Ibd2SqlAdapter,
    Ibd2SqlPhysicalRowExtractor,
    InnochecksumAdapter,
    MysqlBinlogAdapter,
    MysqlBinlogDecoder,
)
from core.application.errors import PrerequisiteError
from core.application.models import EvidenceKind, EvidenceStageRequest, VerificationStatus
from core.application.use_cases.extraction import (
    DecodeBinaryLogsUseCase,
    ExtractPhysicalRowsUseCase,
    ExtractSchemaUseCase,
    RunPageValidationUseCase,
)
from tests.application.fakes import FixedClock, MemoryEvidence
from tests.application.test_extraction_use_cases import MemoryExtractionResults, verified
from tests.fixtures.builders import accounts_schema


SDI = json.dumps([{"object": {"dd_object_type": "Table", "dd_object": {
    "name": "accounts", "schema_ref": "finance", "columns": [
        {"name": "account_id", "hidden": 1, "ordinal_position": 1,
         "column_type_utf8": "int", "is_nullable": False},
    ], "indexes": [{"name": "PRIMARY", "elements": [{"hidden": False, "column_opx": 0}]}],
}}}]).encode()
ROWS = b"INSERT INTO `finance`.`accounts`(`account_id`) VALUES (101);\n"
BINLOG = b"""#260904 20:06:38 server id 1  end_log_pos 100 Query
BEGIN
#260904 20:06:38 server id 1  end_log_pos 150 Write_rows: table id 89
### INSERT INTO `finance`.`accounts`
### SET
###   @1=101
#260904 20:06:38 server id 1  end_log_pos 200 Xid = 7
COMMIT
"""


def completed(stdout=b"", code=0, stderr=b""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class ToolIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ibd = verified(EvidenceKind.IBD)
        self.binlog = verified(EvidenceKind.BINLOG, "binlog-1")
        self.evidence = MemoryEvidence(self.ibd, self.binlog)
        self.results = MemoryExtractionResults()

    def execute(self, use_case, adapter, evidence=None):
        item = evidence or self.ibd
        return use_case(self.evidence, adapter, self.results, FixedClock()).execute(
            EvidenceStageRequest(item.case_id, item.id)
        )

    @patch("subprocess.run")
    def test_schema_wrapper_saves_single_schema_sequence(self, run):
        run.return_value = completed(SDI)
        receipt = self.execute(ExtractSchemaUseCase, Ibd2SdiSchemaExtractor(Ibd2SdiAdapter()))
        self.assertEqual(receipt.item_count, 1)
        self.assertEqual(self.results.schemas[0].table, "accounts")
        run.assert_called_once_with(["ibd2sdi", self.ibd.working_copy_path], capture_output=True)

    @patch("subprocess.run")
    def test_page_validator_connects_directly(self, run):
        run.side_effect = [completed(), completed(b"#PAGE_COUNT\n  2\tIndex page\n")]
        self.execute(RunPageValidationUseCase, InnochecksumAdapter())
        self.assertEqual(self.results.integrity.status, "valid")
        self.assertEqual(self.results.integrity.total_pages, 2)
        self.assertEqual(run.call_args_list[0].args[0],
                         ["innochecksum", self.ibd.working_copy_path])
        self.assertEqual(run.call_args_list[1].args[0],
                         ["innochecksum", "-S", self.ibd.working_copy_path])

    @patch("subprocess.run")
    def test_live_rows_default_and_deleted_rows_opt_in(self, run):
        run.return_value = completed(ROWS)
        adapter = Ibd2SqlAdapter("/tools/ibd2sql/main.py")
        self.execute(ExtractPhysicalRowsUseCase, Ibd2SqlPhysicalRowExtractor(adapter))
        self.assertEqual(run.call_count, 1)
        self.assertFalse(self.results.records[0].is_deleted)
        run.reset_mock()
        receipt = self.execute(ExtractPhysicalRowsUseCase,
                               Ibd2SqlPhysicalRowExtractor(adapter, include_deleted=True))
        self.assertEqual(receipt.item_count, 2)
        self.assertEqual([r.is_deleted for r in self.results.records], [False, True])
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["--delete", "only"])

    @patch("subprocess.run")
    def test_binlog_lookup_maps_columns_and_retains_markers(self, run):
        run.return_value = completed(BINLOG)
        lookup = Mock(return_value=accounts_schema())
        receipt = self.execute(DecodeBinaryLogsUseCase,
                               MysqlBinlogDecoder(MysqlBinlogAdapter(), lookup), self.binlog)
        lookup.assert_called_with("finance", "accounts")
        self.assertEqual(self.results.decoded.events[0].after["account_id"], 101)
        self.assertTrue(self.results.decoded.markers)
        self.assertEqual(self.results.decoded.warnings, ())
        self.assertEqual(receipt.item_count,
                         len(self.results.decoded.events) + len(self.results.decoded.markers))
        self.assertEqual(run.call_args.args[0][-1], self.binlog.working_copy_path)

    @patch("subprocess.run")
    def test_missing_schema_warning_reaches_persistence(self, run):
        run.return_value = completed(BINLOG)
        self.execute(DecodeBinaryLogsUseCase,
                     MysqlBinlogDecoder(MysqlBinlogAdapter(), lambda db, table: None), self.binlog)
        self.assertEqual(self.results.decoded.events, ())
        self.assertEqual(self.results.decoded.warnings[0].code, "SCHEMA_NOT_FOUND")

    @patch("subprocess.run")
    def test_failure_propagates_without_saving_partial_rows(self, run):
        run.side_effect = [completed(ROWS), completed(code=1, stderr=b"failed")]
        with self.assertRaises(RuntimeError):
            self.execute(ExtractPhysicalRowsUseCase, Ibd2SqlPhysicalRowExtractor(
                Ibd2SqlAdapter("/tools/main.py"), include_deleted=True))
        self.assertIsNone(self.results.records)

    @patch("subprocess.run")
    def test_schema_and_binlog_failures_do_not_save_results(self, run):
        run.return_value = completed(code=1, stderr=b"failed")
        with self.assertRaises(RuntimeError):
            self.execute(ExtractSchemaUseCase, Ibd2SdiSchemaExtractor(Ibd2SdiAdapter()))
        with self.assertRaises(RuntimeError):
            self.execute(DecodeBinaryLogsUseCase,
                         MysqlBinlogDecoder(MysqlBinlogAdapter(), lambda db, table: None),
                         self.binlog)
        self.assertIsNone(self.results.schemas)
        self.assertIsNone(self.results.decoded)

    @patch("subprocess.run")
    def test_unverified_evidence_never_launches_a_tool(self, run):
        self.evidence.save(replace(
            self.ibd, verification_status=VerificationStatus.REGISTERED,
            working_copy_path=None, working_copy_sha256=None,
        ))
        with self.assertRaises(PrerequisiteError):
            self.execute(ExtractSchemaUseCase, Ibd2SdiSchemaExtractor(Ibd2SdiAdapter()))
        run.assert_not_called()
