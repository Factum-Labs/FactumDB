"""StateReconstructionService: replaying correlated events into record histories.

It never invents a value. Every rule here exists to keep some form of invention
out:

* Events replay in log-sequence and position order, never by timestamp.
  `mysqlbinlog` prints one-second resolution converted from server-local time, so
  events inside a single transaction routinely share a timestamp. Log position is
  the physical write order and the only total order the evidence actually
  provides.

* The starting state comes from the first observed event and nothing is
  extrapolated backwards past it.

* A column absent from a partial row image keeps its last observed value, or
  stays unobserved if it never had one. It is never defaulted or zero-filled.

* Rolled-back and uncommitted events are recorded but not applied, because "we
  did not observe a commit" is not the same as "it committed".

The one place the service draws an inference is the before-image check: when an
event's before-image disagrees with the state our replay had reached, that is
positive evidence of a change we did not observe. It is the only gap detectable
without the binlog index saying so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from core.domain.models.canonical import (
    BinlogEvent,
    EventRef,
    PhysicalRecord,
    ProvenanceReference,
    Schema,
)
from core.domain.models.correlation import CorrelationResult, RecordCorrelation
from core.domain.models.findings import Finding, SubjectKind, SubjectRef
from core.domain.models.history import (
    FieldChange,
    HistoryStep,
    ReconstructedState,
    ReconstructionResult,
    RecordHistory,
    StepKind,
)
from core.domain.models.identity import RecordKey, UnrenderableKey, render_key_value
from core.domain.models.transactions import (
    CoverageWindow,
    GroupingResult,
    TransactionStatus,
)
from core.domain.models.values import (
    UNOBSERVED,
    Presence,
    UndecodableValue,
    Value,
    compare,
)
from core.domain.ordering import FileSequence, event_sort_key
from core.domain.ports import EvidenceContext, PhysicalRecordSource, SchemaCatalog
from core.domain.rules import rule


class _Working:
    """Mutable replay state. Frozen into a `ReconstructedState` when done."""

    __slots__ = ("derived_from", "last_ref", "presence", "values")

    def __init__(self, columns: Sequence[str]) -> None:
        self.values: dict[str, Value] = {c: UNOBSERVED for c in columns}
        self.presence: Presence = Presence.UNKNOWN
        self.derived_from: dict[str, EventRef] = {}
        self.last_ref: EventRef | None = None

    def apply(self, image: Mapping[str, Value], ref: EventRef) -> None:
        for column in self.values:
            if column in image:
                self.values[column] = image[column]
                self.derived_from[column] = ref
        self.last_ref = ref

    def freeze(self) -> ReconstructedState:
        return ReconstructedState(
            values=dict(self.values),
            presence=self.presence,
            derived_from=dict(self.derived_from),
            last_ref=self.last_ref,
        )

    def snapshot(self) -> dict[str, Value]:
        return dict(self.values)


class StateReconstructionService:
    """Replays correlated events chronologically into record histories."""

    def __init__(
        self,
        schemas: SchemaCatalog,
        physical: PhysicalRecordSource,
        evidence: EvidenceContext,
    ) -> None:
        self._schemas = schemas
        self._physical = physical
        self._evidence = evidence

    # ── Entry point ──────────────────────────────────────────────────────────

    def reconstruct(
        self, grouping: GroupingResult, correlation: CorrelationResult
    ) -> ReconstructionResult:
        sequence = FileSequence(self._evidence.inventory())
        findings: list[Finding] = []
        events = self._event_index(grouping)

        histories = [
            self._build_history(record, events, grouping, sequence, findings)
            for record in correlation.records
        ]
        return ReconstructionResult(
            histories=tuple(h for h in histories if h is not None),
            findings=tuple(findings),
        )

    # ── One record ───────────────────────────────────────────────────────────

    def _build_history(
        self,
        correlation: RecordCorrelation,
        events: Mapping[EventRef, BinlogEvent],
        grouping: GroupingResult,
        sequence: FileSequence,
        findings: list[Finding],
    ) -> RecordHistory | None:
        key = correlation.record.to_key()
        schema = self._schemas.schema_for(key.database, key.table)
        if schema is None:
            return None

        columns = [c.name for c in schema.columns_in_order()]
        ordered = self._ordered_events(correlation, events, sequence)

        durable_state = _Working(columns)
        speculative = _Working(columns)
        observed: dict[str, list[Value]] = {c: [] for c in columns}
        partial_columns: set[str] = set()

        steps: list[HistoryStep] = []
        record_findings: list[Finding] = []
        mismatch = False
        subject = SubjectRef(SubjectKind.RECORD, correlation.record.id)

        if ordered:
            steps.append(self._seed(ordered[0], durable_state, speculative, subject))
            record_findings.append(steps[0].findings[0])

        gaps = self._gaps_for(correlation, grouping)

        for event in ordered:
            transaction = grouping.transaction_for(event.ref)
            status = transaction.status if transaction else None
            durable = transaction.durable if transaction else False

            kind, rule_id = self._classify(transaction, status, event.event_type)

            # Every step cites its rule, including the ordinary ones. A history
            # where only the exceptions are explained leaves an examiner unable
            # to check the reasoning behind the steps that shaped the state.
            step_findings: list[Finding] = [
                self._finding(
                    rule_id,
                    subject,
                    {
                        "record": correlation.record.id,
                        "source_file": event.source_file,
                        "log_position": str(event.log_position),
                        "column_count": str(len(event.after or {})),
                        "count": "1",
                    },
                    (event.provenance,),
                )
            ]

            if durable and self._before_image_disagrees(event, durable_state, schema):
                mismatch = True
                differing = self._differing_columns(event, durable_state, schema)
                step_findings.append(
                    self._finding(
                        "R-HIST-008",
                        subject,
                        {
                            "record": correlation.record.id,
                            "source_file": event.source_file,
                            "log_position": str(event.log_position),
                            "columns": ", ".join(differing),
                        },
                        (event.provenance,),
                    )
                )

            before_values = durable_state.snapshot()
            presence_before = durable_state.presence

            self._apply(event, speculative, observed, columns, partial_columns, None, subject)
            if durable:
                self._apply(
                    event,
                    durable_state,
                    None,
                    columns,
                    partial_columns,
                    step_findings,
                    subject,
                )

            after_values = durable_state.snapshot() if durable else before_values
            record_findings.extend(step_findings)
            steps.append(
                HistoryStep(
                    index=len(steps),
                    kind=kind,
                    durable=durable,
                    rule_id=rule_id,
                    presence_before=presence_before,
                    presence_after=durable_state.presence if durable else presence_before,
                    changes=self._changes(columns, before_values, after_values),
                    transaction_id=transaction.id if transaction else None,
                    transaction_status=status,
                    ref=event.ref,
                    timestamp=event.timestamp,
                    findings=tuple(step_findings),
                    provenance=event.provenance,
                )
            )

        steps.extend(self._alias_steps(correlation, len(steps), subject, record_findings))
        steps.extend(self._gap_steps(gaps, len(steps), subject, record_findings))

        physical_step = self._physical_step(correlation, schema, len(steps), subject)
        if physical_step is not None:
            steps.append(physical_step)
            record_findings.extend(physical_step.findings)

        findings.extend(record_findings)
        return RecordHistory(
            record=correlation.record,
            method=correlation.method,
            steps=tuple(steps),
            earliest_state=self._earliest(ordered, columns),
            final_log_state=durable_state.freeze(),
            speculative_state=speculative.freeze(),
            observed_values={c: tuple(v) for c, v in observed.items() if v},
            partial_image_columns=tuple(sorted(partial_columns)),
            coverage_gaps_touching=gaps,
            before_image_mismatch=mismatch,
            findings=tuple(record_findings),
        )

    # ── Replay mechanics ─────────────────────────────────────────────────────

    @staticmethod
    def _classify(
        transaction: object | None,
        status: TransactionStatus | None,
        event_type: str,
    ) -> tuple[StepKind, str]:
        """What this step is, and the rule that says how it is treated.

        Durability is asked first: an event that never took effect is described
        by *why* it did not, not by what it would have done. Only for a durable
        event does the kind of change matter.
        """
        if transaction is None:
            return StepKind.UNCOMMITTED_EVENT, "R-HIST-006"
        if status is TransactionStatus.ROLLED_BACK:
            return StepKind.ROLLED_BACK_EVENT, "R-HIST-005"
        if status is TransactionStatus.INCOMPLETE:
            return StepKind.UNCOMMITTED_EVENT, "R-HIST-006"
        if event_type == "DELETE":
            return StepKind.EVENT, "R-HIST-004"
        return StepKind.EVENT, "R-HIST-003"

    def _apply(
        self,
        event: BinlogEvent,
        state: _Working,
        observed: dict[str, list[Value]] | None,
        columns: Sequence[str],
        partial_columns: set[str],
        step_findings: list[Finding] | None,
        subject: SubjectRef,
    ) -> None:
        if event.event_type == "DELETE":
            state.presence = Presence.ABSENT
            state.last_ref = event.ref
            return

        image = event.after or {}
        state.apply(image, event.ref)
        state.presence = Presence.PRESENT

        if observed is not None:
            for column, value in image.items():
                if column in observed:
                    observed[column].append(value)

        # A row image that omits columns is a limitation on what we can say, not
        # a reason to invent values for the rest.
        absent = [c for c in columns if c not in image]
        if absent:
            partial_columns.update(absent)
            if step_findings is not None:
                step_findings.append(
                    self._finding(
                        "R-HIST-007",
                        subject,
                        {"record": subject.id, "columns": ", ".join(sorted(absent))},
                        (event.provenance,),
                    )
                )

        if step_findings is not None:
            for column, value in sorted(image.items()):
                if isinstance(value, UndecodableValue):
                    step_findings.append(
                        self._finding(
                            "R-HIST-010",
                            subject,
                            {
                                "record": subject.id,
                                "column": column,
                                "source_file": event.source_file,
                                "log_position": str(event.log_position),
                            },
                            (event.provenance,),
                        )
                    )

    def _seed(
        self,
        first: BinlogEvent,
        durable: _Working,
        speculative: _Working,
        subject: SubjectRef,
    ) -> HistoryStep:
        """Establish what was already there, from the first event only.

        An INSERT proves the row was absent. An UPDATE or DELETE carries a
        before-image showing what it held. Nothing earlier is extrapolated.
        """
        if first.event_type == "INSERT":
            durable.presence = Presence.ABSENT
            speculative.presence = Presence.ABSENT
        else:
            image = first.before or {}
            for state in (durable, speculative):
                state.apply(image, first.ref)
                state.presence = Presence.PRESENT

        finding = self._finding(
            "R-HIST-002",
            subject,
            {
                "record": subject.id,
                "source_file": first.source_file,
                "log_position": str(first.log_position),
            },
            (first.provenance,),
        )
        return HistoryStep(
            index=0,
            kind=StepKind.EARLIEST_OBSERVED,
            durable=True,
            rule_id="R-HIST-002",
            presence_before=Presence.UNKNOWN,
            presence_after=durable.presence,
            ref=first.ref,
            timestamp=first.timestamp,
            findings=(finding,),
            provenance=first.provenance,
        )

    def _earliest(
        self, ordered: Sequence[BinlogEvent], columns: Sequence[str]
    ) -> ReconstructedState:
        state = _Working(columns)
        if not ordered:
            return state.freeze()
        first = ordered[0]
        if first.event_type == "INSERT":
            state.presence = Presence.ABSENT
        else:
            state.apply(first.before or {}, first.ref)
            state.presence = Presence.PRESENT
        return state.freeze()

    # ── Before-image consistency ─────────────────────────────────────────────

    def _before_image_disagrees(
        self, event: BinlogEvent, state: _Working, schema: Schema
    ) -> bool:
        return bool(self._differing_columns(event, state, schema))

    def _differing_columns(
        self, event: BinlogEvent, state: _Working, schema: Schema
    ) -> tuple[str, ...]:
        """Columns where the event's before-image contradicts our replay.

        Only columns we have actually observed are checked - an unobserved
        column cannot contradict anything. Comparison goes through the same
        `compare` the reconciliation service uses, so an undecodable or
        incomparable value never counts as a disagreement.
        """
        if event.before is None or state.last_ref is None:
            return ()
        differing: list[str] = []
        for column, claimed in sorted(event.before.items()):
            held = state.values.get(column, UNOBSERVED)
            if held is UNOBSERVED:
                continue
            result = compare(held, claimed, schema.column(column))
            if result.comparable and result.equal is False:
                differing.append(column)
        return tuple(differing)

    # ── Extra steps ──────────────────────────────────────────────────────────

    def _alias_steps(
        self,
        correlation: RecordCorrelation,
        start: int,
        subject: SubjectRef,
        record_findings: list[Finding],
    ) -> list[HistoryStep]:
        steps: list[HistoryStep] = []
        for offset, alias in enumerate(correlation.identity_aliases):
            finding = self._finding(
                "R-HIST-011",
                subject,
                {
                    "record": correlation.record.id,
                    "previous_key": alias.id,
                    "source_file": "",
                    "log_position": "",
                },
                (),
            )
            record_findings.append(finding)
            steps.append(
                HistoryStep(
                    index=start + offset,
                    kind=StepKind.IDENTITY_CHANGE,
                    durable=True,
                    rule_id="R-HIST-011",
                    findings=(finding,),
                )
            )
        return steps

    def _gaps_for(
        self, correlation: RecordCorrelation, grouping: GroupingResult
    ) -> tuple[CoverageWindow, ...]:
        """Coverage windows that fall inside this record's observed history.

        A record with no events at all still inherits case-wide gaps: a missing
        log could be exactly what explains why nothing was observed for it.
        """
        if not grouping.coverage.gaps:
            return ()
        files = {ref[0] for ref in correlation.log_event_refs}
        relevant = [
            window
            for window in grouping.coverage.gaps
            if window.reason != "truncated_file"
            or window.after_file is None
            or window.after_file in files
            or not files
        ]
        return tuple(relevant)

    def _gap_steps(
        self,
        gaps: Sequence[CoverageWindow],
        start: int,
        subject: SubjectRef,
        record_findings: list[Finding],
    ) -> list[HistoryStep]:
        steps: list[HistoryStep] = []
        for offset, window in enumerate(gaps):
            finding = self._finding(
                "R-HIST-009",
                subject,
                {
                    "record": subject.id,
                    "source_file": window.after_file or "",
                    "log_position": str(window.after_position or ""),
                },
                (),
            )
            record_findings.append(finding)
            steps.append(
                HistoryStep(
                    index=start + offset,
                    kind=StepKind.COVERAGE_GAP,
                    durable=False,
                    rule_id="R-HIST-009",
                    findings=(finding,),
                )
            )
        return steps

    def _physical_step(
        self,
        correlation: RecordCorrelation,
        schema: Schema,
        index: int,
        subject: SubjectRef,
    ) -> HistoryStep | None:
        """The tablespace state, appended as an observation not a replayed change."""
        if correlation.physical is None:
            return None
        record = self._physical_record(correlation, schema)
        if record is None:
            return None

        finding = self._finding(
            "R-HIST-012",
            subject,
            {
                "record": correlation.record.id,
                "page_no": str(record.page_no),
                "page_offset": str(record.page_offset),
            },
            (record.provenance,),
        )
        return HistoryStep(
            index=index,
            kind=StepKind.PHYSICAL_STATE,
            durable=False,
            rule_id="R-HIST-012",
            presence_after=Presence.ABSENT if record.is_deleted else Presence.PRESENT,
            changes=tuple(
                FieldChange(column=c, before=UNOBSERVED, after=record.values.get(c, UNOBSERVED),
                            changed=None)
                for c in sorted(record.values)
            ),
            findings=(finding,),
            provenance=record.provenance,
        )

    def _physical_record(
        self, correlation: RecordCorrelation, schema: Schema
    ) -> PhysicalRecord | None:
        key = correlation.record.to_key()
        for record in self._physical.records_for(key.database, key.table):
            if self._key_of(record, schema) == key:
                if correlation.physical is not None and (
                    record.is_deleted != correlation.physical.is_deleted
                ):
                    continue
                return record
        return None

    @staticmethod
    def _key_of(record: PhysicalRecord, schema: Schema) -> RecordKey | None:
        try:
            values = tuple(
                render_key_value(c.name, record.values[c.name])
                for c in schema.primary_key_columns()
            )
        except (UnrenderableKey, KeyError):
            return None
        return RecordKey(
            database=schema.database,
            table=schema.table,
            columns=tuple(c.name for c in schema.primary_key_columns()),
            values=values,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _event_index(grouping: GroupingResult) -> dict[EventRef, BinlogEvent]:
        index = {g.ref: g.event for t in grouping.transactions for g in t.events}
        index.update({u.ref: u.event for u in grouping.ungrouped_events})
        return index

    @staticmethod
    def _ordered_events(
        correlation: RecordCorrelation,
        events: Mapping[EventRef, BinlogEvent],
        sequence: FileSequence,
    ) -> list[BinlogEvent]:
        found = [events[ref] for ref in correlation.log_event_refs if ref in events]
        return sorted(
            found, key=lambda e: event_sort_key(sequence, e.source_file, e.log_position)
        )

    @staticmethod
    def _changes(
        columns: Sequence[str],
        before: Mapping[str, Value],
        after: Mapping[str, Value],
    ) -> tuple[FieldChange, ...]:
        changes: list[FieldChange] = []
        for column in columns:
            was = before.get(column, UNOBSERVED)
            now = after.get(column, UNOBSERVED)
            if was is UNOBSERVED and now is UNOBSERVED:
                continue
            result = compare(was, now)
            changed = None if not result.comparable else not result.equal
            if changed is False:
                continue
            changes.append(FieldChange(column=column, before=was, after=now, changed=changed))
        return tuple(changes)

    @staticmethod
    def _finding(
        rule_id: str,
        subject: SubjectRef,
        context: dict[str, str],
        provenance: Iterable[ProvenanceReference | None],
    ) -> Finding:
        definition = rule(rule_id)
        return Finding(
            rule_id=rule_id,
            severity=definition.severity,
            subject=subject,
            context=dict(sorted(context.items())),
            provenance=tuple(p for p in provenance if p is not None),
        )
