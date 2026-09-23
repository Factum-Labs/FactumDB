"""Exercise composed stages and their shared data dependencies."""

import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from core.application.models import (
    DecodedBinlog, EvidenceKind, NormalizedEvidence, VerificationStatus,
)
from core.application.orchestration.models import ANALYSIS_STAGES, PipelineStage, StageStatus
from core.application.ports import DomainInputs
from sidecar.composition import (
    ExtractionAdapters, PipelineDependencies, build_analysis_pipeline, build_tool_adapters,
)
from tests.application.fakes import FixedClock, FixedIds, MemoryCases, MemoryEvidence
from tests.application.test_domain_use_cases import repository
from tests.application.test_extraction_use_cases import MemoryExtractionResults, verified
from tests.application.test_orchestrator import MemoryPipelines, MemoryPublisher, a_case
from tests.fixtures.datasets import DS02
from tests.fixtures.builders import integrity
from tests.fixtures.inmemory import (
    InMemoryEventSource, InMemoryPhysicalRecordSource, InMemorySchemaCatalog,
)


class PipelineCompositionTests(unittest.TestCase):
    def setUp(self):
        self.ibd = replace(verified(EvidenceKind.IBD),
                           verification_status=VerificationStatus.REGISTERED,
                           working_copy_path=None, working_copy_sha256=None)
        self.binlog = replace(verified(EvidenceKind.BINLOG, "binlog-1"),
                              verification_status=VerificationStatus.REGISTERED,
                              working_copy_path=None, working_copy_sha256=None)
        self.evidence = MemoryEvidence(self.ibd, self.binlog)
        self.results = MemoryExtractionResults()
        self.domain = repository()
        context = self.domain.inputs.evidence
        self.domain.inputs = None  # Domain data becomes available only after normalization.
        self.copies = Mock()
        self.copies.create.side_effect = lambda case, evidence: f"/working/{evidence.filename}"
        self.hasher = Mock()
        self.hasher.sha256.return_value = "a" * 64
        self.normalizer = Mock()

        def normalize(case_id):
            self.assertIsNotNone(self.results.integrity)
            return NormalizedEvidence(self.results.schemas, self.results.records,
                                      self.results.decoded.events, self.results.decoded.markers)

        self.normalizer.normalize.side_effect = normalize
        original_save = self.results.save_normalized

        def save_normalized(case_id, normalized):
            original_save(case_id, normalized)
            self.domain.inputs = DomainInputs(
                InMemorySchemaCatalog(*normalized.schemas),
                InMemoryEventSource(normalized.events, normalized.markers),
                InMemoryPhysicalRecordSource(*normalized.physical_records), context,
            )

        self.results.save_normalized = save_normalized
        self.validator = Mock()
        self.validator.validate.return_value = integrity()
        self.schema = Mock()
        self.schema.extract.return_value = DS02.schemas
        self.rows = Mock()
        self.rows.extract.return_value = DS02.physical
        self.decoder = Mock()
        self.decoder.decode.return_value = DecodedBinlog(DS02.events, DS02.markers)
        self.decoder_factory = Mock()

        def decoder_for_case(case_id):
            self.assertIsNotNone(self.results.schemas)
            self.assertIsNone(self.domain.inputs)
            return self.decoder

        self.decoder_factory.side_effect = decoder_for_case
        self.pipelines = MemoryPipelines()
        self.progress = MemoryPublisher()
        self.dependencies = PipelineDependencies(
            cases=MemoryCases(a_case()), evidence=self.evidence, copies=self.copies,
            hasher=self.hasher, extraction=self.results, normalizer=self.normalizer,
            domain=self.domain, pipelines=self.pipelines, progress=self.progress,
            ids=FixedIds("run-1"), clock=FixedClock(),
        )
        self.adapters = ExtractionAdapters(
            page_validator=self.validator, schema_extractor=self.schema,
            row_extractor=self.rows, decoder_for_case=self.decoder_factory,
        )

    def test_all_stages_execute_with_data_flow_into_real_domain_services(self):
        pipeline = build_analysis_pipeline(self.dependencies, self.adapters)
        self.copies.create.assert_not_called()
        self.decoder_factory.assert_not_called()
        run = pipeline.run_all(pipeline.start("case-1").id)
        self.assertTrue(run.complete, run)
        self.assertEqual(tuple(s.stage for s in run.stages), ANALYSIS_STAGES)
        self.assertEqual(self.copies.create.call_count, 2)
        self.validator.validate.assert_called_once_with("/working/accounts.ibd")
        self.schema.extract.assert_called_once_with("/working/accounts.ibd")
        self.rows.extract.assert_called_once_with("/working/accounts.ibd")
        self.decoder.decode.assert_called_once_with("/working/binlog.000018")
        self.decoder_factory.assert_called_once_with("case-1")
        self.assertIsNotNone(self.domain.reconciliation)
        self.assertEqual(run.stages[-1].attempts[-1].item_count,
                         len(self.domain.reconciliation.rows))
        self.assertEqual([e.stage for e in self.progress.events
                          if e.status is StageStatus.SUCCEEDED], list(ANALYSIS_STAGES))
        self.assertIs(self.pipelines.get(run.id), run)

    def test_extraction_failure_stops_before_normalization(self):
        self.schema.extract.side_effect = RuntimeError("schema tool failed")
        pipeline = build_analysis_pipeline(self.dependencies, self.adapters)
        run = pipeline.run_all(pipeline.start("case-1").id)
        self.assertEqual(run.state_for(PipelineStage.EXTRACT_SCHEMA).status, StageStatus.FAILED)
        self.rows.extract.assert_not_called()
        self.decoder_factory.assert_not_called()
        self.normalizer.normalize.assert_not_called()
        self.assertIsNone(self.domain.reconciliation)

    def test_hash_mismatch_stops_before_any_tool(self):
        self.hasher.sha256.return_value = "b" * 64
        pipeline = build_analysis_pipeline(self.dependencies, self.adapters)
        run = pipeline.run_all(pipeline.start("case-1").id)
        self.assertEqual(run.stages[0].status, StageStatus.FAILED)
        self.validator.validate.assert_not_called()
        self.schema.extract.assert_not_called()

    def test_normalization_failure_stops_domain_stages(self):
        self.normalizer.normalize.side_effect = RuntimeError("normalization failed")
        pipeline = build_analysis_pipeline(self.dependencies, self.adapters)
        run = pipeline.run_all(pipeline.start("case-1").id)
        self.assertEqual(run.state_for(PipelineStage.NORMALIZE_EVIDENCE).status,
                         StageStatus.FAILED)
        self.assertIsNone(self.domain.grouping)

    @patch("subprocess.run")
    def test_tool_factory_is_lazy_and_resolves_distinct_case_catalogs(self, run):
        catalogs = {case: Mock() for case in ("case-a", "case-b")}
        lookup = Mock(side_effect=catalogs.__getitem__)
        adapters = build_tool_adapters(lookup, ibd2sql_path="/tools/main.py")
        lookup.assert_not_called()
        with patch("adapters.tools.mysqlbinlog_adapter.MysqlBinlogAdapter.decode",
                   return_value=([], [], [])) as decode:
            for case in catalogs:
                adapters.decoder_for_case(case).decode("/working/binlog.000018")
                self.assertIs(decode.call_args.args[1], catalogs[case].schema_for)
        self.assertEqual([c.args[0] for c in lookup.call_args_list], ["case-a", "case-b"])
        run.assert_not_called()
