"""Transaction grouping vocabulary and results.

What `TransactionGroupingService` produces. The enums are cited by the rule
catalogue - a rule that writes an `IncompletenessReason` names the exact member,
and a test checks the link - so they are declared here rather than inside the
service.

See ADR-01 in `docs/correlation-rules.md` for why there are three statuses rather
than the four `Architecture.md` mentions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from core.domain.models.canonical import (
    BinlogEvent,
    BinlogInventory,
    EventRef,
    ProvenanceReference,
)
from core.domain.models.findings import Finding


class TransactionStatus(StrEnum):
    """The three statuses the canonical model and the SQLite CHECK allow.

    Taken verbatim from `TransactionMarker.status` - the adapter observes the
    outcome, the domain does not reinterpret it.
    """

    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    INCOMPLETE = "incomplete"


class IncompletenessReason(StrEnum):
    """Why an incomplete transaction is incomplete.

    `incomplete` says the terminator was not observed; this says why, which is
    what decides whether the gap is bounded (we know a file is missing) or merely
    the edge of what we were given.

    Every value here is written by exactly one rule in the catalogue, and that
    rule's `incompleteness_reason` field names it. The mapping is asserted by
    `tests/domain/test_rules_catalogue.py`, so a value can never be assigned by
    logic that cites no rule.
    """

    #: The last available log simply ends with the transaction still open.
    #: Decided with R-COV-003. The gap is unbounded: we cannot say how much is
    #: missing, only that the record stops here.
    NO_TERMINATOR_IN_RANGE = "no_terminator_in_range"

    #: The index proves a log file between this transaction and its terminator
    #: was not provided. Decided with R-COV-002. The gap is bounded - we know
    #: exactly which file would resolve it, which is a materially stronger
    #: statement than "the evidence stops here".
    LOG_FILE_MISSING_IN_SEQUENCE = "log_file_missing_in_sequence"

    #: Row events with no opening marker, grouped into a synthesised transaction.
    EVENTS_WITHOUT_BEGIN = "events_without_begin"

    #: A marker whose events were not decoded, or could not be claimed.
    MARKER_WITHOUT_EVENTS = "marker_without_events"


@dataclass(frozen=True, slots=True)
class GroupedEvent:
    """One event inside a transaction, with its position in the replay order."""

    order: int
    event: BinlogEvent
    provenance: ProvenanceReference | None = None

    @property
    def ref(self) -> EventRef:
        return self.event.ref


@dataclass(frozen=True, slots=True)
class TransactionGroup:
    """Events the evidence shows were committed, rolled back, or left open together.

    `synthesised` is the important caveat. A synthesised group is **not** a claim
    that its events formed one transaction - it delimits a region of log in which
    no transaction structure was observed at all, so the events stay together and
    ordered instead of scattering. It is never durable, and any display that shows
    it must show that it was synthesised. A group with `synthesised=False`
    corresponds to a marker the adapter actually saw.

    Frontend mapping: `binlogFile` is `source_file` and `binlogPos` is
    `start_position`. The plan's earlier draft duplicated these as separate
    fields; they are properties of the marker already, and storing them twice
    would only create a way for them to disagree.
    """

    id: str
    status: TransactionStatus
    source_file: str
    start_position: int
    end_position: int
    events: tuple[GroupedEvent, ...]
    session_key: str
    incompleteness_reason: IncompletenessReason | None = None
    gtid: str | None = None
    xid: int | None = None
    thread_id: int | None = None
    commit_position: int | None = None
    commit_timestamp: datetime | None = None
    synthesised: bool = False
    findings: tuple[Finding, ...] = ()
    provenance: tuple[ProvenanceReference, ...] = ()

    @property
    def durable(self) -> bool:
        """Whether events in this transaction actually took effect.

        Only a committed transaction is durable. Rolled-back and incomplete ones
        are retained as evidence but never applied to a reconstructed state - for
        incomplete ones because "we did not observe a commit" is not the same as
        "it committed", and assuming otherwise would invent a change.
        """
        return self.status is TransactionStatus.COMMITTED

    @property
    def summary_counts(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for grouped in self.events:
            counts[grouped.event.event_type] = counts.get(grouped.event.event_type, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def tables_touched(self) -> tuple[str, ...]:
        return tuple(sorted({g.event.qualified_name for g in self.events}))


@dataclass(frozen=True, slots=True)
class UngroupedEvent:
    """An event no marker claimed, kept as evidence rather than discarded.

    It stays on the timeline and is never durable. `rule_id` records why it could
    not be placed, so the report can say so rather than the event simply being
    absent.
    """

    event: BinlogEvent
    rule_id: str
    provenance: ProvenanceReference | None = None

    @property
    def ref(self) -> EventRef:
        return self.event.ref


@dataclass(frozen=True, slots=True)
class CoverageWindow:
    """A stretch of history the evidence cannot speak to.

    `missing_file` is bounded - we can name what is absent. `truncated_file` and
    `no_index` are unbounded: we know only that observation stops, not how much
    is beyond it. That difference is what separates a specific statement to an
    examiner from a vague one, so it is carried rather than flattened.
    """

    reason: Literal["missing_file", "truncated_file", "no_index"]
    rule_id: str
    after_file: str | None = None
    after_position: int | None = None
    before_file: str | None = None
    missing_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """What the evidence set can and cannot account for.

    `complete` being False is what later turns a would-be Conflicting into
    Unresolved. It is False whenever anything is unaccounted for, including the
    case where there is no index at all - absence of the index is never read as
    proof that we hold every log.
    """

    observed_files: tuple[str, ...]
    gaps: tuple[CoverageWindow, ...]
    inventory: BinlogInventory | None = None
    findings: tuple[Finding, ...] = ()

    @property
    def complete(self) -> bool:
        return self.inventory is not None and not self.gaps

    def gaps_after(self, source_file: str, sequence_index: int) -> tuple[CoverageWindow, ...]:
        """Windows that begin at or after the given point in the log sequence."""
        return tuple(w for w in self.gaps if w.after_file is None or w.after_file == source_file)


@dataclass(frozen=True, slots=True)
class GroupingResult:
    """Everything `TransactionGroupingService` concluded."""

    transactions: tuple[TransactionGroup, ...]
    ungrouped_events: tuple[UngroupedEvent, ...]
    coverage: CoverageReport
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def event_count(self) -> int:
        return sum(len(t.events) for t in self.transactions) + len(self.ungrouped_events)

    def transaction_for(self, ref: EventRef) -> TransactionGroup | None:
        for transaction in self.transactions:
            for grouped in transaction.events:
                if grouped.ref == ref:
                    return transaction
        return None
