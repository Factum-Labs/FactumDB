"""RecordCorrelationService: linking events and pages to record identities.

Correlation is exact-match only. There is no fuzzy matching and no scoring - a
record identity comes from a primary key the evidence actually expresses, or it
does not come at all. Every branch that cannot produce one reports why instead.

Two places do the real work.

`_resolve_identities` handles primary key updates. A row whose key changes is
still one row, so the before and after images link the two key values into a
chain. But a chain is only followed where it is unambiguous: if merging would
give one key two successors or two predecessors, or close a cycle, the identities
are kept separate and reported. Guessing there would silently merge two records
that the evidence does not say are the same.

`_match_physical` handles the tablespace side. Where two live rows carry the same
key, neither is chosen - the correlation becomes ambiguous, which forces every
downstream comparison for that record to Unresolved rather than comparing against
an arbitrary pick.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from core.domain.models.canonical import (
    BinlogEvent,
    EventRef,
    EventType,
    PhysicalRecord,
    ProvenanceReference,
    Schema,
)
from core.domain.models.correlation import (
    IDENTITY_IMAGE,
    CorrelationEdge,
    CorrelationResult,
    EventCorrelation,
    MatchMethod,
    PhysicalRecordRef,
    RecordCorrelation,
    UnsupportedTable,
)
from core.domain.models.findings import Finding, SubjectKind, SubjectRef
from core.domain.models.identity import (
    KEY_SEPARATOR,
    RecordKey,
    RecordRef,
    UnrenderableKey,
    render_key_value,
)
from core.domain.models.transactions import GroupingResult
from core.domain.models.values import Value
from core.domain.ordering import record_sort_key
from core.domain.ports import EvidenceContext, PhysicalRecordSource, SchemaCatalog
from core.domain.rules import rule


class RecordCorrelationService:
    """Links binlog events and physical rows to logical record identities."""

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

    def correlate(self, grouping: GroupingResult) -> CorrelationResult:
        findings: list[Finding] = []
        events = self._all_events(grouping)

        tables = self._tables_in_play(events)
        unsupported: list[UnsupportedTable] = []
        keyed: dict[EventRef, RecordKey] = {}
        event_results: list[EventCorrelation] = []

        for database, table in tables:
            schema = self._schemas.schema_for(database, table)
            table_events = [e for e in events if (e.database, e.table) == (database, table)]

            problem = self._table_problem(schema, database, table, findings)
            if problem is not None:
                unsupported.append(UnsupportedTable(database, table, problem[1]))
                event_results.extend(
                    self._unsupported_event(e, problem[0], problem[1], grouping)
                    for e in table_events
                )
                continue

            assert schema is not None  # narrowed by _table_problem
            for event in table_events:
                self._key_event(event, schema, keyed, event_results, grouping, findings)

        aliases = self._resolve_identities(events, keyed, findings)
        records = self._build_records(events, keyed, aliases, grouping, findings)
        records = self._attach_physical(records, findings)
        records.extend(self._physical_only(records, tables, findings))

        self._check_namespace_collisions(records, findings)

        records.sort(key=lambda r: record_sort_key(r.record))
        edges = self._build_edges(records, grouping)
        event_results = self._retarget_events(event_results, keyed, aliases)

        return CorrelationResult(
            records=tuple(records),
            edges=edges,
            event_correlations=tuple(
                sorted(event_results, key=lambda c: (c.ref[0], c.ref[1]))
            ),
            unsupported_tables=tuple(sorted(unsupported, key=lambda u: u.qualified_name)),
            findings=tuple(findings),
        )

    # ── Table-level gates ────────────────────────────────────────────────────

    def _table_problem(
        self, schema: Schema | None, database: str, table: str, findings: list[Finding]
    ) -> tuple[MatchMethod, str] | None:
        """Whether this table can be correlated at all.

        Two ways it cannot. Without a schema the row images cannot be
        interpreted. Without a primary key there is no identity that both the log
        and the tablespace express - InnoDB's hidden row id is invisible to
        `mysqlbinlog` - so any identity we produced would be one we invented.
        """
        subject = SubjectRef(SubjectKind.TABLE, f"{database}.{table}")
        if schema is None:
            findings.append(
                self._finding("R-CORR-021", subject, {"table": f"{database}.{table}"}, ())
            )
            return MatchMethod.UNSUPPORTED_NO_SCHEMA, "R-CORR-021"

        if not schema.primary_key_columns():
            findings.append(
                self._finding("R-CORR-020", subject, {"table": schema.qualified_name}, ())
            )
            return MatchMethod.UNSUPPORTED_NO_PK, "R-CORR-020"

        return None

    # ── Keying events ────────────────────────────────────────────────────────

    def _key_event(
        self,
        event: BinlogEvent,
        schema: Schema,
        keyed: dict[EventRef, RecordKey],
        results: list[EventCorrelation],
        grouping: GroupingResult,
        findings: list[Finding],
    ) -> None:
        """Extract the record identity this event carries."""
        # UPDATE keys off its after-image so a key change lands on the new
        # identity; the before-image is picked up separately as an alias.
        image = event.before if IDENTITY_IMAGE[event.event_type] == "before" else event.after
        key = self._key_from_image(event, schema, image, findings)
        if key is None:
            results.append(
                self._unsupported_event(
                    event, MatchMethod.UNSUPPORTED_PARTIAL_KEY, "R-CORR-003", grouping
                )
            )
            return

        keyed[event.ref] = key
        composite = len(key.columns) > 1
        method = MatchMethod.COMPOSITE_PK_EXACT if composite else MatchMethod.PK_EXACT
        results.append(
            EventCorrelation(
                ref=event.ref,
                event_type=event.event_type,
                method=method,
                rule_id="R-CORR-002" if composite else "R-CORR-001",
                transaction_id=self._transaction_id(event.ref, grouping),
                record_id=key.record_id,
            )
        )

    def _key_from_image(
        self,
        event: BinlogEvent,
        schema: Schema,
        image: Mapping[str, Value] | None,
        findings: list[Finding],
    ) -> RecordKey | None:
        if image is None:
            return None
        try:
            values = tuple(
                render_key_value(c.name, image[c.name]) if c.name in image else _missing(c.name)
                for c in schema.primary_key_columns()
            )
        except UnrenderableKey as exc:
            findings.append(
                self._finding(
                    "R-CORR-003",
                    SubjectRef(SubjectKind.EVENT, f"{event.source_file}:{event.log_position}"),
                    {
                        "source_file": event.source_file,
                        "log_position": str(event.log_position),
                        "reason": f"{exc.column}: {exc.reason}",
                    },
                    (event.provenance,),
                )
            )
            return None

        key = RecordKey(
            database=schema.database,
            table=schema.table,
            columns=tuple(c.name for c in schema.primary_key_columns()),
            values=values,
        )
        if key.has_separator_collision:
            findings.append(
                self._finding(
                    "R-ID-002",
                    SubjectRef(SubjectKind.RECORD, key.record_id),
                    {"record": key.record_id, "separator": KEY_SEPARATOR},
                    (event.provenance,),
                )
            )
        return key

    # ── Identity continuity across primary key updates ───────────────────────

    def _resolve_identities(
        self,
        events: Sequence[BinlogEvent],
        keyed: dict[EventRef, RecordKey],
        findings: list[Finding],
    ) -> dict[RecordKey, RecordKey]:
        """Map every key to the canonical identity it belongs to.

        ADR-02: the canonical identity is the terminal (latest) key, because the
        tablespace holds the current key and that makes the physical match
        direct.

        A link is only followed where the evidence determines it. Three shapes
        are refused: one key with two successors, one key with two predecessors,
        and a cycle. Each would require choosing between readings the evidence
        does not distinguish, so the identities stay separate and R-CORR-011 is
        emitted instead.
        """
        successors: dict[RecordKey, set[RecordKey]] = {}
        predecessors: dict[RecordKey, set[RecordKey]] = {}

        for event in events:
            if event.event_type != "UPDATE":
                continue
            before = self._paired_key(event, keyed, "before")
            after = keyed.get(event.ref)
            if before is None or after is None or before == after:
                continue
            successors.setdefault(before, set()).add(after)
            predecessors.setdefault(after, set()).add(before)

        ambiguous: set[RecordKey] = set()
        for key, nexts in successors.items():
            if len(nexts) > 1:
                ambiguous.add(key)
                ambiguous.update(nexts)
        for key, prevs in predecessors.items():
            if len(prevs) > 1:
                ambiguous.add(key)
                ambiguous.update(prevs)

        for key in sorted(successors, key=lambda k: k.record_id):
            if key in ambiguous:
                continue
            if self._closes_cycle(key, successors):
                ambiguous.update(self._chain_members(key, successors))

        for key in sorted(ambiguous, key=lambda k: k.record_id):
            findings.append(
                self._finding(
                    "R-CORR-011",
                    SubjectRef(SubjectKind.RECORD, key.record_id),
                    {
                        "key": key.record_id,
                        "reason": "more than one continuation is consistent with the evidence",
                    },
                    (),
                )
            )

        canonical: dict[RecordKey, RecordKey] = {}
        for key in successors:
            if key in ambiguous:
                continue
            terminal = key
            seen = {key}
            while terminal in successors and terminal not in ambiguous:
                nxt = next(iter(successors[terminal]))
                if nxt in seen or nxt in ambiguous:
                    break
                terminal = nxt
                seen.add(terminal)
            if terminal != key:
                canonical[key] = terminal
        return canonical

    @staticmethod
    def _closes_cycle(start: RecordKey, successors: dict[RecordKey, set[RecordKey]]) -> bool:
        seen = {start}
        current = start
        while current in successors:
            nxt = next(iter(successors[current]))
            if nxt in seen:
                return True
            seen.add(nxt)
            current = nxt
        return False

    @staticmethod
    def _chain_members(
        start: RecordKey, successors: dict[RecordKey, set[RecordKey]]
    ) -> set[RecordKey]:
        members = {start}
        current = start
        while current in successors:
            nxt = next(iter(successors[current]))
            if nxt in members:
                break
            members.add(nxt)
            current = nxt
        return members

    def _paired_key(
        self,
        event: BinlogEvent,
        keyed: dict[EventRef, RecordKey],
        image: str,
    ) -> RecordKey | None:
        """The key held by an event's other row image, if it is renderable."""
        canonical = keyed.get(event.ref)
        if canonical is None:
            return None
        source = event.before if image == "before" else event.after
        if source is None:
            return None
        try:
            values = tuple(render_key_value(c, source[c]) for c in canonical.columns)
        except (UnrenderableKey, KeyError):
            return None
        return RecordKey(
            database=canonical.database,
            table=canonical.table,
            columns=canonical.columns,
            values=values,
        )

    # ── Records ──────────────────────────────────────────────────────────────

    def _build_records(
        self,
        events: Sequence[BinlogEvent],
        keyed: dict[EventRef, RecordKey],
        aliases: dict[RecordKey, RecordKey],
        grouping: GroupingResult,
        findings: list[Finding],
    ) -> list[RecordCorrelation]:
        by_key: dict[RecordKey, list[BinlogEvent]] = {}
        alias_of: dict[RecordKey, set[RecordKey]] = {}

        for event in events:
            key = keyed.get(event.ref)
            if key is None:
                continue
            before = self._paired_key(event, keyed, "before")
            for candidate in (key, before):
                if candidate is None:
                    continue
                resolved = self._canonical(candidate, aliases)
                if resolved != candidate:
                    alias_of.setdefault(resolved, set()).add(candidate)

            canonical = self._canonical(key, aliases)
            by_key.setdefault(canonical, []).append(event)

            # A key change whose continuity was refused leaves the old key with
            # no record of its own, and it would vanish from the report even
            # though a before-image observed it. The event is evidence about
            # both identities, so it appears under both - which is the honest
            # reading when the evidence does not say they are the same row.
            if before is not None:
                before_canonical = self._canonical(before, aliases)
                if before_canonical != canonical:
                    by_key.setdefault(before_canonical, []).append(event)

        records: list[RecordCorrelation] = []
        for key, key_events in by_key.items():
            ordered = sorted(key_events, key=lambda e: (e.source_file, e.log_position))
            record = RecordRef.from_key(key)
            record_findings: list[Finding] = []

            alias_keys = sorted(alias_of.get(key, set()), key=lambda k: k.record_id)
            method = MatchMethod.PK_UPDATE_CONTINUITY if alias_keys else (
                MatchMethod.COMPOSITE_PK_EXACT if len(key.columns) > 1 else MatchMethod.PK_EXACT
            )
            for alias in alias_keys:
                record_findings.append(
                    self._finding(
                        "R-CORR-010",
                        SubjectRef(SubjectKind.RECORD, record.id),
                        {"record": record.id, "previous_key": alias.record_id},
                        (),
                    )
                )

            if self._key_reused_after_delete(ordered):
                record_findings.append(
                    self._finding(
                        "R-CORR-012",
                        SubjectRef(SubjectKind.RECORD, record.id),
                        {"record": record.id},
                        (),
                    )
                )

            findings.extend(record_findings)
            records.append(
                RecordCorrelation(
                    record=record,
                    method=method,
                    log_event_refs=tuple(e.ref for e in ordered),
                    transaction_ids=self._transaction_ids(ordered, grouping),
                    identity_aliases=tuple(RecordRef.from_key(a) for a in alias_keys),
                    findings=tuple(record_findings),
                    provenance=tuple(e.provenance for e in ordered if e.provenance is not None),
                )
            )
        return records

    @staticmethod
    def _key_reused_after_delete(events: Sequence[BinlogEvent]) -> bool:
        """A key deleted and later inserted again is still one record.

        The schema says it is one key, and an examiner reading "accounts:101"
        expects one row with a gap in its life, not two rows.
        """
        seen_delete = False
        for event in events:
            if event.event_type == "DELETE":
                seen_delete = True
            elif event.event_type == "INSERT" and seen_delete:
                return True
        return False

    @staticmethod
    def _canonical(key: RecordKey, aliases: dict[RecordKey, RecordKey]) -> RecordKey:
        current = key
        seen = {key}
        while current in aliases:
            current = aliases[current]
            if current in seen:
                break
            seen.add(current)
        return current

    # ── Physical side ────────────────────────────────────────────────────────

    def _attach_physical(
        self, records: list[RecordCorrelation], findings: list[Finding]
    ) -> list[RecordCorrelation]:
        with_physical: list[RecordCorrelation] = []
        for correlation in records:
            key = correlation.record.to_key()
            if not self._table_has_tablespace(key.database, key.table, findings):
                with_physical.append(_replace(correlation, method=MatchMethod.LOG_ONLY))
                continue
            with_physical.append(self._match_physical(correlation, key, findings))
        return with_physical

    def _match_physical(
        self, correlation: RecordCorrelation, key: RecordKey, findings: list[Finding]
    ) -> RecordCorrelation:
        candidates = self._candidates_for(key)
        if not candidates:
            return _replace(correlation, method=MatchMethod.LOG_ONLY)

        live = [c for c in candidates if not c.is_deleted]
        refs = tuple(self._physical_ref(c) for c in candidates)

        if len(live) > 1:
            findings.append(
                self._finding(
                    "R-CORR-022",
                    SubjectRef(SubjectKind.RECORD, correlation.record.id),
                    {"record": correlation.record.id, "count": str(len(live))},
                    (),
                )
            )
            return _replace(
                correlation,
                method=MatchMethod.AMBIGUOUS,
                physical=None,
                physical_candidates=refs,
            )

        chosen = live[0] if live else candidates[0]
        if live and len(candidates) > len(live):
            findings.append(
                self._finding(
                    "R-CORR-023",
                    SubjectRef(SubjectKind.RECORD, correlation.record.id),
                    {
                        "record": correlation.record.id,
                        "count": str(len(candidates) - len(live)),
                    },
                    (),
                )
            )
        return _replace(
            correlation, physical=self._physical_ref(chosen), physical_candidates=refs
        )

    def _candidates_for(self, key: RecordKey) -> list[PhysicalRecord]:
        matches: list[PhysicalRecord] = []
        for record in self._physical.records_for(key.database, key.table):
            try:
                values = tuple(render_key_value(c, record.values[c]) for c in key.columns)
            except (UnrenderableKey, KeyError):
                continue
            if values == key.values:
                matches.append(record)
        return matches

    def _physical_only(
        self,
        records: Sequence[RecordCorrelation],
        tables: Sequence[tuple[str, str]],
        findings: list[Finding],
    ) -> list[RecordCorrelation]:
        """Rows in the tablespace that no observed event produced."""
        known = {r.record.id for r in records}
        extra: list[RecordCorrelation] = []

        for database, table in tables:
            schema = self._schemas.schema_for(database, table)
            if schema is None or not schema.primary_key_columns():
                continue
            if (database, table) not in self._evidence.tables_with_physical_evidence():
                continue
            for physical in self._physical.records_for(database, table):
                key = self._key_from_physical(physical, schema)
                if key is None or key.record_id in known:
                    continue
                known.add(key.record_id)
                record = RecordRef.from_key(key)
                finding = self._finding(
                    "R-CORR-031",
                    SubjectRef(SubjectKind.RECORD, record.id),
                    {"record": record.id},
                    (physical.provenance,),
                )
                findings.append(finding)
                extra.append(
                    RecordCorrelation(
                        record=record,
                        method=MatchMethod.PHYSICAL_ONLY,
                        physical=self._physical_ref(physical),
                        physical_candidates=(self._physical_ref(physical),),
                        findings=(finding,),
                        provenance=(physical.provenance,) if physical.provenance else (),
                    )
                )
        return extra

    @staticmethod
    def _key_from_physical(record: PhysicalRecord, schema: Schema) -> RecordKey | None:
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

    @staticmethod
    def _physical_ref(record: PhysicalRecord) -> PhysicalRecordRef:
        return PhysicalRecordRef(
            database=record.database,
            table=record.table,
            is_deleted=record.is_deleted,
            page_no=record.page_no,
            page_offset=record.page_offset,
            provenance=record.provenance,
        )

    def _table_has_tablespace(
        self, database: str, table: str, findings: list[Finding]
    ) -> bool:
        """Whether an `.ibd` for this table is in the evidence set.

        Absence means the physical side is unobserved, not that the row is
        missing. Conflating those would turn "we were not given the file" into a
        conflict, which is precisely the false claim the tool exists to avoid.
        """
        if (database, table) in self._evidence.tables_with_physical_evidence():
            return True
        qualified = f"{database}.{table}"
        if not any(
            f.rule_id == "R-CORR-030" and f.context.get("table") == qualified for f in findings
        ):
            findings.append(
                self._finding(
                    "R-CORR-030",
                    SubjectRef(SubjectKind.TABLE, qualified),
                    {"table": qualified},
                    (),
                )
            )
        return False

    # ── Edges ────────────────────────────────────────────────────────────────

    def _build_edges(
        self, records: Sequence[RecordCorrelation], grouping: GroupingResult
    ) -> tuple[CorrelationEdge, ...]:
        order = {t.id: i for i, t in enumerate(grouping.transactions)}
        collected: dict[tuple[str, str, EventType], list[EventRef]] = {}

        for correlation in records:
            for ref in correlation.log_event_refs:
                transaction = grouping.transaction_for(ref)
                if transaction is None:
                    continue
                event = self._event_at(ref, grouping)
                if event is None:
                    continue
                slot = (transaction.id, correlation.record.id, event.event_type)
                collected.setdefault(slot, []).append(ref)

        record_order = {r.record.id: i for i, r in enumerate(records)}
        edges = [
            CorrelationEdge(
                tx_id=tx,
                record_id=rid,
                event_type=kind,
                event_refs=tuple(sorted(refs)),
            )
            for (tx, rid, kind), refs in collected.items()
        ]
        edges.sort(key=lambda e: (order.get(e.tx_id, 0), record_order[e.record_id], e.event_type))
        return tuple(edges)

    @staticmethod
    def _event_at(ref: EventRef, grouping: GroupingResult) -> BinlogEvent | None:
        for transaction in grouping.transactions:
            for grouped in transaction.events:
                if grouped.ref == ref:
                    return grouped.event
        for ungrouped in grouping.ungrouped_events:
            if ungrouped.ref == ref:
                return ungrouped.event
        return None

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _all_events(grouping: GroupingResult) -> list[BinlogEvent]:
        """Every decoded event, grouped or not.

        Ungrouped events are correlated too. They are evidence about a record
        even though their transaction was never observed; excluding them would
        drop a real observation because of a separate gap.
        """
        events = [g.event for t in grouping.transactions for g in t.events]
        events.extend(u.event for u in grouping.ungrouped_events)
        return sorted(events, key=lambda e: (e.source_file, e.log_position))

    def _tables_in_play(self, events: Sequence[BinlogEvent]) -> list[tuple[str, str]]:
        tables = {(e.database, e.table) for e in events}
        tables |= set(self._evidence.tables_with_physical_evidence())
        return sorted(tables)

    @staticmethod
    def _transaction_id(ref: EventRef, grouping: GroupingResult) -> str | None:
        transaction = grouping.transaction_for(ref)
        return transaction.id if transaction else None

    @staticmethod
    def _transaction_ids(
        events: Sequence[BinlogEvent], grouping: GroupingResult
    ) -> tuple[str, ...]:
        order = {t.id: i for i, t in enumerate(grouping.transactions)}
        ids = {
            t.id for e in events if (t := grouping.transaction_for(e.ref)) is not None
        }
        return tuple(sorted(ids, key=lambda i: order.get(i, 0)))

    def _unsupported_event(
        self,
        event: BinlogEvent,
        method: MatchMethod,
        rule_id: str,
        grouping: GroupingResult,
    ) -> EventCorrelation:
        return EventCorrelation(
            ref=event.ref,
            event_type=event.event_type,
            method=method,
            rule_id=rule_id,
            transaction_id=self._transaction_id(event.ref, grouping),
            record_id=None,
        )

    @staticmethod
    def _retarget_events(
        results: Sequence[EventCorrelation],
        keyed: dict[EventRef, RecordKey],
        aliases: dict[RecordKey, RecordKey],
    ) -> list[EventCorrelation]:
        """Point each event at the canonical identity, not its key at the time."""
        retargeted: list[EventCorrelation] = []
        for result in results:
            key = keyed.get(result.ref)
            if key is None:
                retargeted.append(result)
                continue
            canonical = RecordCorrelationService._canonical(key, aliases)
            record_id = canonical.record_id
            method = (
                MatchMethod.PK_UPDATE_CONTINUITY if canonical != key else result.method
            )
            retargeted.append(
                EventCorrelation(
                    ref=result.ref,
                    event_type=result.event_type,
                    method=method,
                    rule_id="R-CORR-010" if canonical != key else result.rule_id,
                    transaction_id=result.transaction_id,
                    record_id=record_id,
                )
            )
        return retargeted

    def _check_namespace_collisions(
        self, records: Sequence[RecordCorrelation], findings: list[Finding]
    ) -> None:
        """Two databases with the same table name give colliding record ids.

        The ids are a frontend contract and use the short table name, so the
        collision is real. Records stay separate internally by qualified name;
        this makes the ambiguity visible to anyone reading an id alone.
        """
        by_table: dict[str, set[str]] = {}
        for correlation in records:
            key = correlation.record.to_key()
            by_table.setdefault(key.table, set()).add(key.database)
        for table, databases in sorted(by_table.items()):
            if len(databases) > 1:
                findings.append(
                    self._finding(
                        "R-ID-003",
                        SubjectRef(SubjectKind.TABLE, table),
                        {"table": table, "databases": ", ".join(sorted(databases))},
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


def _missing(column: str) -> str:
    """Raise from inside a comprehension when a key column is absent.

    A partial key is not a weaker identity, it is no identity - so this aborts
    the whole key rather than yielding a placeholder that could be matched
    against something.
    """
    raise UnrenderableKey(column, "key column not present in the row image")


def _replace(correlation: RecordCorrelation, **changes: object) -> RecordCorrelation:
    """Rebuild a frozen correlation with some fields changed."""
    data = {
        "record": correlation.record,
        "method": correlation.method,
        "log_event_refs": correlation.log_event_refs,
        "transaction_ids": correlation.transaction_ids,
        "physical": correlation.physical,
        "physical_candidates": correlation.physical_candidates,
        "identity_aliases": correlation.identity_aliases,
        "findings": correlation.findings,
        "provenance": correlation.provenance,
    }
    data.update(changes)
    return RecordCorrelation(**data)  # type: ignore[arg-type]
