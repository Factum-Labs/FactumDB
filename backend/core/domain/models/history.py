"""What `StateReconstructionService` produces: a record's observed history.

Three states are carried rather than one, because they answer different
questions and collapsing them would let the report assert something the evidence
does not support:

    earliest_state      what the first observed event says was already there
    final_log_state     replaying only durable (committed) events
    speculative_state   replaying everything, including rolled back and
                        uncommitted events

`final_log_state` is the engine's claim about what the database held.
`speculative_state` is not a claim at all - it exists so the engine can notice
that a value in the tablespace equals one produced by a transaction that was
rolled back, and report that as an observation without concluding anything about
how it got there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from core.domain.models.canonical import EventRef, ProvenanceReference
from core.domain.models.correlation import MatchMethod
from core.domain.models.findings import Finding
from core.domain.models.identity import RecordRef
from core.domain.models.transactions import CoverageWindow, TransactionStatus
from core.domain.models.values import UNOBSERVED, Presence, Value


class StepKind(StrEnum):
    """What one entry in a record's history represents."""

    EARLIEST_OBSERVED = "earliest_observed_state"
    EVENT = "event"
    ROLLED_BACK_EVENT = "rolled_back_event"
    UNCOMMITTED_EVENT = "uncommitted_event"
    IDENTITY_CHANGE = "identity_change"
    COVERAGE_GAP = "coverage_gap"
    PHYSICAL_STATE = "physical_state"


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One column moving from one value to another.

    `changed` is None when either side is unobserved. "We cannot tell whether
    this changed" is a third answer, and flattening it to False would present an
    absence of evidence as evidence of stability.
    """

    column: str
    before: Value
    after: Value
    changed: bool | None


@dataclass(frozen=True, slots=True)
class HistoryStep:
    """One point in a record's observed history.

    `durable` is what separates a step that contributes to the reconstructed
    state from one that is only recorded. A rolled-back update is a real
    observation about the evidence and a non-event as far as the database is
    concerned, and the history has to show both.
    """

    index: int
    kind: StepKind
    durable: bool
    rule_id: str
    presence_before: Presence = Presence.UNKNOWN
    presence_after: Presence = Presence.UNKNOWN
    changes: tuple[FieldChange, ...] = ()
    transaction_id: str | None = None
    transaction_status: TransactionStatus | None = None
    ref: EventRef | None = None
    timestamp: datetime | None = None
    findings: tuple[Finding, ...] = ()
    provenance: ProvenanceReference | None = None


@dataclass(frozen=True, slots=True)
class ReconstructedState:
    """A record's columns at one point, with where each value came from.

    Every schema column is present. Columns no evidence speaks to hold
    UNOBSERVED rather than being omitted, so a caller cannot mistake a column we
    never saw for one that does not exist.
    """

    values: Mapping[str, Value]
    presence: Presence
    derived_from: Mapping[str, EventRef] = field(default_factory=dict)
    last_ref: EventRef | None = None

    def value(self, column: str) -> Value:
        return self.values.get(column, UNOBSERVED)

    @property
    def observed_columns(self) -> tuple[str, ...]:
        return tuple(sorted(c for c, v in self.values.items() if v is not UNOBSERVED))


@dataclass(frozen=True, slots=True)
class RecordHistory:
    """Everything the evidence shows about one record over time."""

    record: RecordRef
    method: MatchMethod
    steps: tuple[HistoryStep, ...]
    earliest_state: ReconstructedState
    final_log_state: ReconstructedState
    speculative_state: ReconstructedState
    observed_values: Mapping[str, tuple[Value, ...]] = field(default_factory=dict)
    partial_image_columns: tuple[str, ...] = ()
    coverage_gaps_touching: tuple[CoverageWindow, ...] = ()
    before_image_mismatch: bool = False
    findings: tuple[Finding, ...] = ()

    @property
    def gap_touched(self) -> bool:
        """Whether anything limits what this history can be held to.

        This is the flag that later turns a would-be Conflicting into
        Unresolved, so it is deliberately inclusive: a missing log, a truncated
        one, or a before-image that disagreed with our replay all count. The last
        of those is the only gap detectable without the index saying so.
        """
        return bool(self.coverage_gaps_touching) or self.before_image_mismatch

    def produced(self, column: str) -> tuple[Value, ...]:
        return self.observed_values.get(column, ())


@dataclass(frozen=True, slots=True)
class ReconstructionResult:
    histories: tuple[RecordHistory, ...]
    findings: tuple[Finding, ...] = ()

    def history(self, record_id: str) -> RecordHistory | None:
        for entry in self.histories:
            if entry.record.id == record_id:
                return entry
        return None
