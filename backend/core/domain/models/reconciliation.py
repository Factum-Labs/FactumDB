"""What `ReconciliationService` produces: log-derived state against the tablespace.

Two granularities, both needed. `FieldReconciliation` is per column and maps 1:1
onto the frontend's `ReconRow`. `RecordReconciliation` rolls those up, which is
what the graph nodes label and what an examiner reads first.

The typed `log`/`phys` values are carried alongside rendered `log_display`/
`phys_display` strings. The frontend type collapses both into plain strings,
which cannot distinguish a real SQL NULL from an undecodable value from a column
no evidence ever mentioned - three different facts. The engine keeps them apart
and lets the presentation layer flatten them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.domain.models.canonical import ProvenanceReference
from core.domain.models.classification import SEVERITY, ReconResult, is_flag_result
from core.domain.models.findings import Finding
from core.domain.models.identity import RecordRef
from core.domain.models.transactions import CoverageReport
from core.domain.models.values import Value

#: The pseudo-field carrying whether the record exists at all, as distinct from
#: what its columns hold. Always emitted first for every record.
PRESENCE_FIELD = "record presence"


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """Where both sides of one comparison came from."""

    log: tuple[ProvenanceReference, ...] = ()
    physical: ProvenanceReference | None = None
    transaction_id: str | None = None


#: Shared default. Safe to share because the class is frozen and every field it
#: holds is immutable, so no `field(default_factory=...)` is needed - which
#: matters here, since `FieldReconciliation` has a column named `field` and the
#: two would shadow each other.
NO_PROVENANCE = FieldProvenance()


@dataclass(frozen=True, slots=True)
class FieldReconciliation:
    """One column compared, or the reason it could not be."""

    record_id: str
    field: str
    log: Value
    phys: Value
    log_display: str
    phys_display: str
    result: ReconResult
    rule_id: str
    comparable: bool
    provenance: FieldProvenance = NO_PROVENANCE
    findings: tuple[Finding, ...] = ()

    @property
    def is_presence(self) -> bool:
        return self.field == PRESENCE_FIELD


@dataclass(frozen=True, slots=True)
class RecordReconciliation:
    """A record's fields and the verdict rolled up from them."""

    record: RecordRef
    fields: tuple[FieldReconciliation, ...]
    rollup: ReconResult
    rollup_rule_id: str
    rollup_label: str
    triggers: tuple[tuple[str, ReconResult], ...] = ()
    findings: tuple[Finding, ...] = ()

    @property
    def flagged(self) -> bool:
        """Whether this record gets a correlation graph.

        Deliberately driven by the presence of a Conflicting or Unresolved
        *field*, not by the roll-up. A record can roll up to Partial while still
        holding one unresolved column that an examiner needs to see.
        """
        return any(is_flag_result(f.result) for f in self.fields)

    @property
    def severity(self) -> ReconResult | None:
        """Most severe field result - what the label and node colour follow."""
        if not self.fields:
            return None
        return max((f.result for f in self.fields), key=lambda r: SEVERITY[r])

    @property
    def counts(self) -> Mapping[ReconResult, int]:
        tally: dict[ReconResult, int] = {}
        for entry in self.fields:
            tally[entry.result] = tally.get(entry.result, 0) + 1
        return dict(sorted(tally.items(), key=lambda kv: kv[0].value))


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    records: tuple[RecordReconciliation, ...]
    rows: tuple[FieldReconciliation, ...]
    coverage: CoverageReport
    findings: tuple[Finding, ...] = ()

    @property
    def counts(self) -> Mapping[ReconResult, int]:
        tally: dict[ReconResult, int] = {}
        for row in self.rows:
            tally[row.result] = tally.get(row.result, 0) + 1
        return dict(sorted(tally.items(), key=lambda kv: kv[0].value))

    def record(self, record_id: str) -> RecordReconciliation | None:
        for entry in self.records:
            if entry.record.id == record_id:
                return entry
        return None

    def rows_for(self, record_id: str) -> tuple[FieldReconciliation, ...]:
        return tuple(r for r in self.rows if r.record_id == record_id)
