"""TransactionGroupingService: which events were committed together.

The markers are the authority. The adapter parses BEGIN, GTID, XID and ROLLBACK
out of `mysqlbinlog` output; this service never re-parses text, it only decides
what the markers mean and what the gaps between them imply.

The single most important thing this service refuses to do is infer membership
from adjacency. Concurrent sessions interleave in the binary log, so two events
next to each other by position may belong to different transactions. Where a
session identifier is unavailable, events are left ungrouped rather than assigned
to a transaction that merely surrounds them - a plausible-looking wrong grouping
is worse than an admitted gap, because it would silently attribute one session's
changes to another.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from core.domain.models.canonical import (
    BinlogEvent,
    BinlogInventory,
    EventRef,
    ProvenanceReference,
    TransactionMarker,
)
from core.domain.models.findings import Finding, Severity, SubjectKind, SubjectRef
from core.domain.models.transactions import (
    CoverageReport,
    CoverageWindow,
    GroupedEvent,
    GroupingResult,
    IncompletenessReason,
    TransactionGroup,
    TransactionStatus,
    UngroupedEvent,
)
from core.domain.ordering import FileSequence, basename, event_sort_key
from core.domain.ports import EventSource, EvidenceContext
from core.domain.rules import rule


class TransactionGroupingService:
    """Groups decoded binlog events into the transactions the evidence shows."""

    def __init__(self, evidence: EvidenceContext) -> None:
        self._evidence = evidence

    # ── Entry point ──────────────────────────────────────────────────────────

    def group(self, source: EventSource) -> GroupingResult:
        events = list(source.events())
        markers = list(source.markers())
        inventory = self._evidence.inventory()
        sequence = FileSequence(inventory)

        findings: list[Finding] = []
        by_ref = self._index_events(events, findings)

        claimed: set[EventRef] = set()
        transactions: list[TransactionGroup] = []

        coverage = self._build_coverage(inventory, sequence, events, markers, findings)

        for marker in self._sorted_markers(markers, sequence):
            transactions.append(
                self._build_group(marker, by_ref, claimed, sequence, coverage, findings)
            )

        leading, orphans = self._split_unclaimed(by_ref, claimed, markers, sequence)
        if leading:
            transactions.append(self._synthesise_group(leading, sequence, findings))

        ungrouped = tuple(
            UngroupedEvent(
                event=event,
                rule_id="R-GRP-011",
                provenance=self._provenance_for(event, findings),
            )
            for event in orphans
        )
        for entry in ungrouped:
            findings.append(
                self._finding(
                    "R-GRP-011",
                    SubjectRef(SubjectKind.EVENT, f"{entry.ref[0]}:{entry.ref[1]}"),
                    {"source_file": entry.ref[0], "log_position": str(entry.ref[1])},
                    (entry.provenance,),
                )
            )

        transactions.sort(key=lambda t: (sequence.sort_key(t.source_file), t.start_position, t.id))
        transactions = self._resolve_ids(transactions, sequence, findings)

        return GroupingResult(
            transactions=tuple(transactions),
            ungrouped_events=tuple(
                sorted(ungrouped, key=lambda u: event_sort_key(sequence, u.ref[0], u.ref[1]))
            ),
            coverage=coverage,
            findings=tuple(findings),
        )

    # ── Indexing ─────────────────────────────────────────────────────────────

    def _index_events(
        self, events: Sequence[BinlogEvent], findings: list[Finding]
    ) -> dict[EventRef, BinlogEvent]:
        """Index by `(source_file, log_position)`, reporting any collision.

        Two events cannot share a position in one log, so a duplicate means the
        evidence set is inconsistent - the same file registered twice, or a relay
        log mixed in. The first is kept and both are reported.
        """
        by_ref: dict[EventRef, BinlogEvent] = {}
        for event in events:
            if event.ref in by_ref:
                findings.append(
                    self._finding(
                        "R-GRP-013",
                        SubjectRef(SubjectKind.EVENT, f"{event.source_file}:{event.log_position}"),
                        {
                            "source_file": event.source_file,
                            "log_position": str(event.log_position),
                        },
                        (self._provenance_for(event, findings),),
                    )
                )
                continue
            by_ref[event.ref] = event
        return by_ref

    @staticmethod
    def _sorted_markers(
        markers: Sequence[TransactionMarker], sequence: FileSequence
    ) -> list[TransactionMarker]:
        def key(m: TransactionMarker) -> tuple[tuple[int, str], int, str]:
            return (sequence.sort_key(m.source_file), m.start_position, m.gtid or "")

        return sorted(markers, key=key)

    # ── Claiming events ──────────────────────────────────────────────────────

    def _claim(
        self,
        marker: TransactionMarker,
        by_ref: dict[EventRef, BinlogEvent],
        claimed: set[EventRef],
        findings: list[Finding],
        transaction_id: str,
    ) -> list[BinlogEvent]:
        """Decide which events belong to this marker.

        Two paths. When the marker lists its event positions - the normal case -
        those are taken verbatim and nothing else is considered. When it lists
        none, membership falls back to session identity within the marker's
        position range, and if no session identifier is available on both sides
        the events are refused rather than guessed at.
        """
        if marker.event_positions:
            return self._claim_by_position(marker, by_ref, claimed, findings, transaction_id)
        return self._claim_by_session(marker, by_ref, claimed, findings, transaction_id)

    def _claim_by_position(
        self,
        marker: TransactionMarker,
        by_ref: dict[EventRef, BinlogEvent],
        claimed: set[EventRef],
        findings: list[Finding],
        transaction_id: str,
    ) -> list[BinlogEvent]:
        taken: list[BinlogEvent] = []
        for position in marker.event_positions:
            ref = (marker.source_file, position)
            event = by_ref.get(ref)
            if event is None:
                findings.append(
                    self._finding(
                        "R-GRP-009",
                        SubjectRef(SubjectKind.TRANSACTION, transaction_id),
                        {
                            "transaction": transaction_id,
                            "source_file": marker.source_file,
                            "log_position": str(position),
                        },
                        (self._marker_provenance(marker),),
                    )
                )
                continue
            taken.append(event)
            claimed.add(ref)

        # An event inside the range the marker did not list is left alone: it may
        # belong to an interleaved session, and claiming it would assert a
        # membership the marker itself does not state.
        for ref, event in by_ref.items():
            if (
                ref[0] == marker.source_file
                and marker.start_position <= ref[1] <= marker.end_position
                and ref[1] not in marker.event_positions
            ):
                findings.append(
                    self._finding(
                        "R-GRP-010",
                        SubjectRef(SubjectKind.EVENT, f"{ref[0]}:{ref[1]}"),
                        {
                            "transaction": transaction_id,
                            "source_file": ref[0],
                            "log_position": str(ref[1]),
                        },
                        (self._provenance_for(event, findings),),
                    )
                )
        return taken

    def _claim_by_session(
        self,
        marker: TransactionMarker,
        by_ref: dict[EventRef, BinlogEvent],
        claimed: set[EventRef],
        findings: list[Finding],
        transaction_id: str,
    ) -> list[BinlogEvent]:
        in_range = [
            event
            for ref, event in by_ref.items()
            if ref[0] == marker.source_file
            and marker.start_position <= ref[1] <= marker.end_position
            and ref not in claimed
        ]
        if not in_range:
            return []

        if marker.thread_id is None or any(e.thread_id is None for e in in_range):
            # This is the "never assume sequential" rule made concrete. Position
            # adjacency is not evidence of membership, so nothing is claimed.
            findings.append(
                self._finding(
                    "R-GRP-008",
                    SubjectRef(SubjectKind.TRANSACTION, transaction_id),
                    {"transaction": transaction_id, "count": str(len(in_range))},
                    (self._marker_provenance(marker),),
                )
            )
            return []

        taken = [e for e in in_range if e.thread_id == marker.thread_id]
        for event in taken:
            claimed.add(event.ref)
        return taken

    # ── Building groups ──────────────────────────────────────────────────────

    def _build_group(
        self,
        marker: TransactionMarker,
        by_ref: dict[EventRef, BinlogEvent],
        claimed: set[EventRef],
        sequence: FileSequence,
        coverage: CoverageReport,
        findings: list[Finding],
    ) -> TransactionGroup:
        provisional_id = self._provisional_id(marker)
        events = self._claim(marker, by_ref, claimed, findings, provisional_id)
        ordered = sorted(
            events, key=lambda e: event_sort_key(sequence, e.source_file, e.log_position)
        )

        status = TransactionStatus(marker.status)
        reason = None
        group_findings: list[Finding] = []

        if status is TransactionStatus.INCOMPLETE:
            reason, rule_id = self._incompleteness(marker, ordered, sequence, coverage)
            group_findings.append(
                self._finding(
                    rule_id,
                    SubjectRef(SubjectKind.TRANSACTION, provisional_id),
                    {
                        "transaction": provisional_id,
                        "source_file": marker.source_file,
                        "missing_files": ", ".join(
                            self._missing_after(marker, sequence, coverage)
                        ),
                    },
                    (self._marker_provenance(marker),),
                )
            )
        elif status is TransactionStatus.ROLLED_BACK:
            group_findings.append(
                self._finding(
                    "R-GRP-003",
                    SubjectRef(SubjectKind.TRANSACTION, provisional_id),
                    {"transaction": provisional_id},
                    (self._marker_provenance(marker),),
                )
            )
        else:
            group_findings.append(
                self._finding(
                    "R-GRP-001" if marker.gtid else "R-GRP-002",
                    SubjectRef(SubjectKind.TRANSACTION, provisional_id),
                    {
                        "transaction": provisional_id,
                        "gtid": marker.gtid or "",
                        "xid": str(marker.xid) if marker.xid is not None else "",
                    },
                    (self._marker_provenance(marker),),
                )
            )

        findings.extend(group_findings)

        # Only a committed transaction has a commit to point at. Recording an
        # end position as a "commit position" for a rolled-back or unterminated
        # transaction would assert an event that was never observed.
        committed = status is TransactionStatus.COMMITTED

        return TransactionGroup(
            id=provisional_id,
            status=status,
            source_file=marker.source_file,
            start_position=marker.start_position,
            end_position=marker.end_position,
            events=tuple(
                GroupedEvent(order=i, event=e, provenance=self._provenance_for(e, findings))
                for i, e in enumerate(ordered)
            ),
            session_key=self._session_key(marker),
            incompleteness_reason=reason,
            gtid=marker.gtid,
            xid=marker.xid,
            thread_id=marker.thread_id,
            commit_position=marker.end_position if committed else None,
            commit_timestamp=ordered[-1].timestamp if committed and ordered else None,
            findings=tuple(group_findings),
            provenance=_present(self._marker_provenance(marker)),
        )

    def _incompleteness(
        self,
        marker: TransactionMarker,
        events: Sequence[BinlogEvent],
        sequence: FileSequence,
        coverage: CoverageReport,
    ) -> tuple[IncompletenessReason, str]:
        """Why this transaction is incomplete, and the rule that says so.

        Ordered most-specific first. A marker that claimed nothing has a defect in
        its content, which is a more precise statement than anything about its
        terminator. Otherwise the question is whether the index can name the file
        that would have held the terminator: if it can, the gap is bounded; if it
        cannot - including when there is no index at all - it is not.
        """
        if not events:
            return IncompletenessReason.MARKER_WITHOUT_EVENTS, "R-GRP-006"
        if self._missing_after(marker, sequence, coverage):
            return IncompletenessReason.LOG_FILE_MISSING_IN_SEQUENCE, "R-GRP-014"
        return IncompletenessReason.NO_TERMINATOR_IN_RANGE, "R-GRP-004"

    @staticmethod
    def _missing_after(
        marker: TransactionMarker, sequence: FileSequence, coverage: CoverageReport
    ) -> tuple[str, ...]:
        """Missing files that sit after this marker in the server's log sequence.

        Empty when there is no index, because a file we were never told about
        cannot be named - which is exactly why R-GRP-014 cannot apply then.
        """
        if coverage.inventory is None:
            return ()
        here = sequence.index(marker.source_file)
        return tuple(
            name
            for name in coverage.inventory.missing_files
            if sequence.index(basename(name)) > here
        )

    @staticmethod
    def _session_key(marker: TransactionMarker) -> str:
        if marker.gtid:
            return marker.gtid
        if marker.thread_id is not None:
            return f"{marker.source_file}:{marker.thread_id}"
        return f"{marker.source_file}:{marker.start_position}"

    # ── Unclaimed events ─────────────────────────────────────────────────────

    def _split_unclaimed(
        self,
        by_ref: dict[EventRef, BinlogEvent],
        claimed: set[EventRef],
        markers: Sequence[TransactionMarker],
        sequence: FileSequence,
    ) -> tuple[list[BinlogEvent], list[BinlogEvent]]:
        """Separate the leading run from mid-stream orphans.

        The leading run is every unclaimed event that precedes *every* marker in
        the evidence. That is observable: nothing at all comes before it, so the
        earliest log we hold demonstrably begins part-way through a transaction.
        An unclaimed event anywhere else has no such backing - markers exist
        before it and none claimed it - so it is grouped with nothing.

        With no markers at all the whole set is a leading run: there is no
        observed structure anywhere, which is the same situation over a wider
        span.
        """
        unclaimed = sorted(
            (e for ref, e in by_ref.items() if ref not in claimed),
            key=lambda e: event_sort_key(sequence, e.source_file, e.log_position),
        )
        if not unclaimed:
            return [], []

        if not markers:
            return unclaimed, []

        first_marker = min(
            (*sequence.sort_key(m.source_file), m.start_position) for m in markers
        )
        leading: list[BinlogEvent] = []
        orphans: list[BinlogEvent] = []
        for event in unclaimed:
            key = (*sequence.sort_key(event.source_file), event.log_position)
            (leading if key < first_marker else orphans).append(event)
        return leading, orphans

    def _synthesise_group(
        self, events: Sequence[BinlogEvent], sequence: FileSequence, findings: list[Finding]
    ) -> TransactionGroup:
        """Container for a region of log with no observed transaction structure.

        Not an assertion that these events formed one transaction - they may span
        several. It says only that no boundary was observable here, and it is
        flagged `synthesised` so nothing downstream mistakes it for a transaction
        the adapter actually saw.
        """
        ordered = sorted(
            events, key=lambda e: event_sort_key(sequence, e.source_file, e.log_position)
        )
        first = ordered[0]
        suffix = basename(first.source_file).rpartition(".")[2] or basename(first.source_file)
        group_id = f"TX-SYNTH-{suffix}@{first.log_position}"

        finding = self._finding(
            "R-GRP-005",
            SubjectRef(SubjectKind.TRANSACTION, group_id),
            {"count": str(len(ordered)), "source_file": first.source_file},
            (self._provenance_for(first, findings),),
        )
        findings.append(finding)

        return TransactionGroup(
            id=group_id,
            status=TransactionStatus.INCOMPLETE,
            source_file=first.source_file,
            start_position=first.log_position,
            end_position=ordered[-1].log_position,
            events=tuple(
                GroupedEvent(order=i, event=e, provenance=self._provenance_for(e, findings))
                for i, e in enumerate(ordered)
            ),
            session_key=f"{first.source_file}:synthesised",
            incompleteness_reason=IncompletenessReason.EVENTS_WITHOUT_BEGIN,
            synthesised=True,
            findings=(finding,),
            provenance=_present(self._provenance_for(first, findings)),
        )

    # ── Identifiers ──────────────────────────────────────────────────────────

    @staticmethod
    def _provisional_id(marker: TransactionMarker) -> str:
        if marker.gtid and ":" in marker.gtid:
            return f"TX-{marker.gtid.rsplit(':', 1)[1]}"
        suffix = basename(marker.source_file).rpartition(".")[2] or basename(marker.source_file)
        return f"TX-{suffix}@{marker.start_position}"

    def _resolve_ids(
        self,
        transactions: list[TransactionGroup],
        sequence: FileSequence,
        findings: list[Finding],
    ) -> list[TransactionGroup]:
        """Disambiguate GTID-derived ids and report duplicates.

        `TX-1452` reads well and matches the worked example in the docs, but the
        sequence number is only unique within one GTID UUID. With more than one
        server UUID in the evidence the id has to carry the UUID too. Ids stay
        derived from the evidence either way, so re-running produces the same
        ones - no counters, nothing minted.
        """
        uuids = {
            t.gtid.rsplit(":", 1)[0] for t in transactions if t.gtid and ":" in t.gtid
        }
        seen: dict[str, list[TransactionGroup]] = {}
        for transaction in transactions:
            seen.setdefault(transaction.id, []).append(transaction)

        if len(uuids) <= 1:
            for gtid_id, group in seen.items():
                if len(group) > 1 and group[0].gtid:
                    findings.append(
                        self._finding(
                            "R-GRP-012",
                            SubjectRef(SubjectKind.TRANSACTION, gtid_id),
                            {"gtid": group[0].gtid or "", "count": str(len(group))},
                            group[0].provenance,
                        )
                    )
            return transactions

        resolved: list[TransactionGroup] = []
        for transaction in transactions:
            if transaction.gtid and ":" in transaction.gtid:
                server, sequence_number = transaction.gtid.rsplit(":", 1)
                new_id = f"TX-{server[:8]}-{sequence_number}"
                resolved.append(_with_id(transaction, new_id))
                findings.append(
                    self._finding(
                        "R-TXID-001",
                        SubjectRef(SubjectKind.TRANSACTION, new_id),
                        {"transaction": new_id, "gtid": transaction.gtid},
                        transaction.provenance,
                    )
                )
            else:
                resolved.append(transaction)
        return resolved

    # ── Coverage ─────────────────────────────────────────────────────────────

    def _build_coverage(
        self,
        inventory: BinlogInventory | None,
        sequence: FileSequence,
        events: Sequence[BinlogEvent],
        markers: Sequence[TransactionMarker],
        findings: list[Finding],
    ) -> CoverageReport:
        observed = tuple(sorted({basename(e.source_file) for e in events}))
        gaps: list[CoverageWindow] = []
        coverage_findings: list[Finding] = []

        if inventory is None:
            window = CoverageWindow(reason="no_index", rule_id="R-COV-001")
            gaps.append(window)
            coverage_findings.append(
                self._finding("R-COV-001", SubjectRef(SubjectKind.EVIDENCE, "binlog-index"), {}, ())
            )
        else:
            present = [basename(f) for f in inventory.listed_files if basename(f) not in {
                basename(m) for m in inventory.missing_files
            }]
            for missing in inventory.missing_files:
                name = basename(missing)
                index = sequence.index(name)
                before = next((f for f in present if sequence.index(f) > index), None)
                after = next(
                    (f for f in reversed(present) if sequence.index(f) < index), None
                )
                gaps.append(
                    CoverageWindow(
                        reason="missing_file",
                        rule_id="R-COV-002",
                        after_file=after,
                        before_file=before,
                        missing_files=(name,),
                    )
                )
                coverage_findings.append(
                    self._finding(
                        "R-COV-002",
                        SubjectRef(SubjectKind.EVIDENCE, name),
                        {"source_file": name},
                        (),
                    )
                )

        for marker in markers:
            if marker.status == "incomplete" and not self._missing_after_raw(
                marker, sequence, inventory
            ):
                gaps.append(
                    CoverageWindow(
                        reason="truncated_file",
                        rule_id="R-COV-003",
                        after_file=basename(marker.source_file),
                        after_position=marker.start_position,
                    )
                )
                coverage_findings.append(
                    self._finding(
                        "R-COV-003",
                        SubjectRef(SubjectKind.EVIDENCE, basename(marker.source_file)),
                        {
                            "source_file": basename(marker.source_file),
                            "transaction": self._provisional_id(marker),
                        },
                        (self._marker_provenance(marker),),
                    )
                )

        findings.extend(coverage_findings)
        return CoverageReport(
            observed_files=observed,
            gaps=tuple(gaps),
            inventory=inventory,
            findings=tuple(coverage_findings),
        )

    @staticmethod
    def _missing_after_raw(
        marker: TransactionMarker, sequence: FileSequence, inventory: BinlogInventory | None
    ) -> tuple[str, ...]:
        if inventory is None:
            return ()
        here = sequence.index(marker.source_file)
        return tuple(
            basename(name)
            for name in inventory.missing_files
            if sequence.index(basename(name)) > here
        )

    # ── Provenance and findings ──────────────────────────────────────────────

    def _provenance_for(
        self, event: BinlogEvent, findings: list[Finding]
    ) -> ProvenanceReference | None:
        if event.provenance is not None:
            return event.provenance
        recorded = self._evidence.provenance_for(event.ref)
        if recorded is not None:
            return recorded
        self._note_missing_provenance(event.source_file, findings)
        return None

    def _marker_provenance(self, marker: TransactionMarker) -> ProvenanceReference | None:
        return marker.provenance

    def _note_missing_provenance(self, source_file: str, findings: list[Finding]) -> None:
        """Report an unbacked source file once, not once per event."""
        if any(
            f.rule_id == "R-PROV-001" and f.context.get("source_file") == source_file
            for f in findings
        ):
            return
        findings.append(
            self._finding(
                "R-PROV-001",
                SubjectRef(SubjectKind.EVIDENCE, source_file),
                {"source_file": source_file},
                (),
            )
        )

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


def _present(provenance: ProvenanceReference | None) -> tuple[ProvenanceReference, ...]:
    """Drop an absent provenance rather than carrying a None into the result.

    A missing tool run is already reported once as R-PROV-001; a None sitting in
    a provenance tuple would let a report render an empty citation, which reads
    as a citation that failed rather than one that was never recorded.
    """
    return () if provenance is None else (provenance,)


def _with_id(transaction: TransactionGroup, new_id: str) -> TransactionGroup:
    """Rebuild a frozen group under a new id, keeping everything else."""
    return TransactionGroup(
        id=new_id,
        status=transaction.status,
        source_file=transaction.source_file,
        start_position=transaction.start_position,
        end_position=transaction.end_position,
        events=transaction.events,
        session_key=transaction.session_key,
        incompleteness_reason=transaction.incompleteness_reason,
        gtid=transaction.gtid,
        xid=transaction.xid,
        thread_id=transaction.thread_id,
        commit_position=transaction.commit_position,
        commit_timestamp=transaction.commit_timestamp,
        synthesised=transaction.synthesised,
        findings=transaction.findings,
        provenance=transaction.provenance,
    )


_ = Severity  # re-exported for callers building findings against this service
