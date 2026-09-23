"""Applicability decisions must distinguish absent evidence from failed processing."""

import unittest
from dataclasses import asdict, replace

from core.application.errors import NotFoundError, PrerequisiteError
from core.application.models import EvidenceKind, NormalizedEvidence
from core.application.orchestration.models import (
    PipelineStage, StageAttempt, StageOutcome, StageStatus,
)
from core.application.use_cases._support import require_verified_evidence
from sidecar.composition import build_analysis_pipeline
from tests.application.fakes import FIXED_NOW, MemoryEvidence
from tests.application.test_extraction_use_cases import verified
from tests.application import test_pipeline_composition as fixtures


class StageApplicabilityTests(unittest.TestCase):
    def setUp(self):
        # Reuse the composed test infrastructure without inheriting its test methods.
        self.fixture = fixtures.PipelineCompositionTests()
        self.fixture.setUp()
        f = self.fixture
        f.normalizer.normalize.side_effect = lambda case_id: NormalizedEvidence(
            f.results.schemas or (), f.results.records or (),
            f.results.decoded.events if f.results.decoded else (),
            f.results.decoded.markers if f.results.decoded else (),
        )
        f.decoder_factory.side_effect = None
        f.decoder_factory.return_value = f.decoder

    def run_case(self, *items):
        f = self.fixture
        f.evidence.items.clear()
        for item in items:
            f.evidence.save(item)
        pipeline = build_analysis_pipeline(f.dependencies, f.adapters)
        return pipeline.run_all(pipeline.start("case-1").id)

    def assert_skipped(self, run, stage, reason):
        state = run.state_for(stage)
        self.assertEqual(state.status, StageStatus.SKIPPED)
        attempt = state.attempts[-1]
        self.assertEqual(attempt.status, StageStatus.SKIPPED)
        self.assertEqual(attempt.skip_reason, reason)
        self.assertEqual(attempt.item_count, 0)
        self.assertIsNotNone(attempt.finished_at)
        self.assertEqual(asdict(attempt)["skip_reason"], reason)
        event = next(e for e in self.fixture.progress.events
                     if e.stage is stage and e.status is StageStatus.SKIPPED)
        self.assertEqual(event.message, reason)

    def test_binlog_only_skips_all_ibd_stages_and_completes(self):
        f = self.fixture
        run = self.run_case(f.binlog)
        self.assertTrue(run.complete, run)
        for stage in (PipelineStage.VALIDATE_PAGES, PipelineStage.EXTRACT_SCHEMA,
                      PipelineStage.EXTRACT_PHYSICAL_ROWS):
            self.assert_skipped(run, stage, "No ibd evidence registered in this case")
        f.validator.validate.assert_not_called()
        f.schema.extract.assert_not_called()
        f.rows.extract.assert_not_called()
        f.decoder.decode.assert_called_once()
        self.assertEqual(f.progress.events[-1].completed_stages, 10)

    def test_ibd_only_skips_decode_without_resolving_catalog(self):
        f = self.fixture
        run = self.run_case(f.ibd)
        self.assertTrue(run.complete, run)
        self.assert_skipped(run, PipelineStage.DECODE_BINARY_LOGS,
                            "No binlog evidence registered in this case")
        f.decoder_factory.assert_not_called()
        f.decoder.decode.assert_not_called()
        f.schema.extract.assert_called_once()

    def test_mixed_evidence_has_no_skipped_stages(self):
        run = self.run_case(self.fixture.ibd, self.fixture.binlog)
        self.assertTrue(run.complete)
        self.assertTrue(all(s.status is StageStatus.SUCCEEDED for s in run.stages))

    def test_empty_and_index_only_cases_fail_verification(self):
        f = self.fixture
        for items in ((), (replace(f.binlog, kind=EvidenceKind.BINLOG_INDEX),)):
            with self.subTest(items=items):
                self.setUp()
                run = self.run_case(*items)
                self.assertEqual(run.stages[0].status, StageStatus.FAILED)
                self.assertEqual(run.stages[0].attempts[-1].error_code, "PrerequisiteError")
                self.assertTrue(all(s.status is StageStatus.PENDING for s in run.stages[1:]))
                self.fixture.copies.create.assert_not_called()
                self.fixture.validator.validate.assert_not_called()

    def test_other_case_evidence_does_not_make_stage_applicable(self):
        run = self.run_case(self.fixture.ibd, replace(self.fixture.binlog, case_id="case-2"))
        self.assertTrue(run.complete)
        self.assert_skipped(run, PipelineStage.DECODE_BINARY_LOGS,
                            "No binlog evidence registered in this case")

    def test_zero_extracted_rows_is_success_not_skip(self):
        self.fixture.rows.extract.return_value = ()
        run = self.run_case(self.fixture.ibd)
        state = run.state_for(PipelineStage.EXTRACT_PHYSICAL_ROWS)
        self.assertEqual(state.status, StageStatus.SUCCEEDED)
        self.assertEqual(state.attempts[-1].item_count, 0)
        self.assertIsNone(state.attempts[-1].skip_reason)

    def test_invalid_verified_metadata_is_rejected(self):
        for changes in ({"working_copy_sha256": "b" * 64}, {"working_copy_path": " "}):
            with self.subTest(changes=changes):
                item = replace(verified(EvidenceKind.IBD), **changes)
                with self.assertRaisesRegex(PrerequisiteError, "working copy"):
                    require_verified_evidence(
                        MemoryEvidence(item), item.case_id, item.id, {EvidenceKind.IBD},
                    )

    def test_missing_case_rejected_before_creating_run(self):
        f = self.fixture
        pipeline = build_analysis_pipeline(f.dependencies, f.adapters)
        with self.assertRaises(NotFoundError):
            pipeline.start("missing")
        self.assertEqual(f.pipelines.runs, {})

    def test_skip_records_require_reason_and_zero_count(self):
        with self.assertRaises(ValueError):
            StageOutcome(skip_reason=" ")
        with self.assertRaises(ValueError):
            StageOutcome(item_count=1, skip_reason="No evidence")
        with self.assertRaises(ValueError):
            StageAttempt(1, StageStatus.SKIPPED, FIXED_NOW)
