"""Runs all four domain services in pipeline order over one dataset.

This is the whole correlation engine, assembled the way the application layer
will assemble it. Everything below the ports is pure, so the same call produces
the same bytes on any machine - which is what the repeatability tests assert.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.models.correlation import CorrelationResult
from core.domain.models.history import ReconstructionResult
from core.domain.models.reconciliation import ReconciliationResult
from core.domain.models.transactions import GroupingResult
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.record_reconciliation import ReconciliationService
from core.domain.services.state_reconstruction import StateReconstructionService
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.datasets import Dataset
from tests.fixtures.inmemory import (
    InMemoryEventSource,
    InMemoryEvidenceContext,
    InMemoryPhysicalRecordSource,
    InMemorySchemaCatalog,
)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Every stage's output, so a test can assert at whichever level it means."""

    grouping: GroupingResult
    correlation: CorrelationResult
    reconstruction: ReconstructionResult
    reconciliation: ReconciliationResult

    @property
    def cited_rules(self) -> tuple[str, ...]:
        """Every rule the engine cited anywhere in this run, sorted.

        Wider than the findings alone. A `rule_id` carried on an event
        correlation or a reconciliation row is a citation too - it is what the
        report renders on the provenance line - so a rule reachable only that way
        is still live reasoning, not dead.
        """
        rule_ids = {f.rule_id for f in self.grouping.findings}
        rule_ids |= {f.rule_id for f in self.correlation.findings}
        rule_ids |= {f.rule_id for f in self.reconstruction.findings}
        rule_ids |= {f.rule_id for f in self.reconciliation.findings}
        rule_ids |= {c.rule_id for c in self.correlation.event_correlations}
        rule_ids |= {r.rule_id for r in self.reconciliation.rows}
        rule_ids |= {r.rollup_rule_id for r in self.reconciliation.records}
        rule_ids |= {s.rule_id for h in self.reconstruction.histories for s in h.steps}
        return tuple(sorted(rule_ids))


def run_pipeline(dataset: Dataset) -> PipelineResult:
    """Grouping, then correlation, then reconstruction, then reconciliation.

    The order is Architecture.md section 3.4's, and each stage consumes only what
    the previous ones produced.
    """
    schemas = InMemorySchemaCatalog(*dataset.schemas)
    physical = InMemoryPhysicalRecordSource(*dataset.physical)
    evidence = InMemoryEvidenceContext(
        inventory=dataset.inventory,
        integrity=dict(dataset.integrity),
        physical_tables=dataset.resolved_physical_tables,
    )

    grouping = TransactionGroupingService(evidence).group(
        InMemoryEventSource(dataset.events, dataset.markers)
    )
    correlation = RecordCorrelationService(schemas, physical, evidence).correlate(grouping)
    reconstruction = StateReconstructionService(schemas, physical, evidence).reconstruct(
        grouping, correlation
    )
    reconciliation = ReconciliationService(schemas, physical, evidence).reconcile(
        reconstruction, correlation, grouping.coverage
    )
    return PipelineResult(grouping, correlation, reconstruction, reconciliation)
