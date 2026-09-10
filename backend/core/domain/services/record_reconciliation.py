"""ReconciliationService: reconstructed state against the physical tablespace.

Named `record_reconciliation` to match `record_correlation`, and to keep it
distinct from `models/reconciliation.py`, which holds the shapes it produces.

The whole service turns on one distinction. When a log-derived value and a
tablespace value differ, that is either a **conflict** - the evidence genuinely
disagrees - or it is **unresolved** - a log we were not given could contain the
change that explains it. Getting that wrong in the permissive direction means
presenting an evidence gap as tampering, which is the worst thing this tool could
do. It is decided in one place, at the bottom of `_classify`, by whether the
record's coverage is complete.

The ladder is total and its branches are mutually exclusive: every field receives
exactly one classification and nothing falls through. The order is not arbitrary
- each step sits where the reason it reports is the most specific one available.
An unsupported column type is a better explanation than "these are different
types"; an ambiguous correlation is a better explanation than "there is no
physical value", because the ambiguity is *why* there is none.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from core.domain.models.canonical import (
    Column,
    PhysicalRecord,
    ProvenanceReference,
    Schema,
)
from core.domain.models.classification import SEVERITY, ReconResult
from core.domain.models.correlation import (
    CorrelationResult,
    RecordCorrelation,
    UnsupportedTable,
)
from core.domain.models.findings import Finding, SubjectKind, SubjectRef
from core.domain.models.history import ReconstructionResult, RecordHistory
from core.domain.models.identity import (
    RecordKey,
    RecordRef,
    UnrenderableKey,
    render_key_value,
)
from core.domain.models.reconciliation import (
    PRESENCE_FIELD,
    FieldProvenance,
    FieldReconciliation,
    ReconciliationResult,
    RecordReconciliation,
)
from core.domain.models.transactions import CoverageReport
from core.domain.models.values import (
    UNOBSERVED,
    Presence,
    UndecodableValue,
    Value,
    compare,
    render,
)
from core.domain.ordering import record_sort_key
from core.domain.ports import EvidenceContext, PhysicalRecordSource, SchemaCatalog
from core.domain.rules import rule

#: Field results that mean a real comparison happened.
_COMPARED = (ReconResult.EXACT, ReconResult.STRONG, ReconResult.CONFLICTING)


class ReconciliationService:
    """Compares reconstructed record state with the physical tablespace."""

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

    def reconcile(
        self,
        reconstruction: ReconstructionResult,
        correlation: CorrelationResult,
        coverage: CoverageReport,
    ) -> ReconciliationResult:
        findings: list[Finding] = []
        records: list[RecordReconciliation] = []

        if not coverage.complete:
            # A case-level notice only. It must never downgrade individual
            # comparisons, or a clean case collapses into a wall of caveats.
            findings.append(
                self._finding("R-COV-005", SubjectRef(SubjectKind.CASE, "case"), {}, ())
            )

        for history in reconstruction.histories:
            match = correlation.record(history.record.id)
            if match is not None:
                records.append(self._reconcile_record(history, match, findings))

        for table in correlation.unsupported_tables:
            records.append(self._unsupported_table(table, findings))

        records.sort(key=lambda r: record_sort_key(r.record))
        return ReconciliationResult(
            records=tuple(records),
            rows=tuple(row for record in records for row in record.fields),
            coverage=coverage,
            findings=tuple(findings),
        )

    # ── One record ───────────────────────────────────────────────────────────

    def _reconcile_record(
        self,
        history: RecordHistory,
        correlation: RecordCorrelation,
        findings: list[Finding],
    ) -> RecordReconciliation:
        key = correlation.record.to_key()
        schema = self._schemas.schema_for(key.database, key.table)
        physical_values = self._physical_values(correlation, schema)
        integrity = self._evidence.integrity_for(key.database, key.table)
        damaged = integrity is not None and integrity.status != "valid"
        status = integrity.status if integrity is not None else "valid"
        supported = self._evidence.supported_data_types()

        fields = [self._presence_row(history, correlation, physical_values, findings)]
        if schema is not None:
            fields.extend(
                self._field_row(
                    history,
                    correlation,
                    column,
                    physical_values,
                    damaged,
                    status,
                    supported,
                    findings,
                )
                for column in schema.columns_in_order()
            )
        return self._roll_up(correlation.record, tuple(fields), findings)

    # ── The ladder ───────────────────────────────────────────────────────────

    def _field_row(
        self,
        history: RecordHistory,
        correlation: RecordCorrelation,
        column: Column,
        physical_values: dict[str, Value] | None,
        damaged: bool,
        integrity_status: str,
        supported: frozenset[str],
        findings: list[Finding],
    ) -> FieldReconciliation:
        log_value = history.final_log_state.value(column.name)
        phys_value = (
            UNOBSERVED
            if physical_values is None
            else physical_values.get(column.name, UNOBSERVED)
        )
        subject = SubjectRef(SubjectKind.FIELD, f"{correlation.record.id}.{column.name}")
        context = {
            "record": correlation.record.id,
            "field": column.name,
            "log": render(log_value),
            "phys": render(phys_value),
            "data_type": column.data_type,
        }

        result, rule_id, extra = self._classify(
            history,
            correlation,
            column,
            log_value,
            phys_value,
            damaged,
            integrity_status,
            supported,
            context,
            subject,
        )

        row_findings = [self._finding(rule_id, subject, context, ()), *extra]
        findings.extend(row_findings)

        return FieldReconciliation(
            record_id=correlation.record.id,
            field=column.name,
            log=log_value,
            phys=phys_value,
            log_display=render(log_value),
            phys_display=render(phys_value),
            result=result,
            rule_id=rule_id,
            comparable=result in _COMPARED,
            provenance=self._field_provenance(history, correlation, column.name),
            findings=tuple(row_findings),
        )

    def _classify(
        self,
        history: RecordHistory,
        correlation: RecordCorrelation,
        column: Column,
        log_value: Value,
        phys_value: Value,
        damaged: bool,
        integrity_status: str,
        supported: frozenset[str],
        context: dict[str, str],
        subject: SubjectRef,
    ) -> tuple[ReconResult, str, list[Finding]]:
        """R-RECON-000. Top down, first match wins, total and exclusive."""
        extra: list[Finding] = []

        # 1. The column's type has never been validated, so comparing it would
        #    rest on decoding we have not verified.
        if column.data_type.lower() not in supported:
            return ReconResult.UNSUPPORTED, "R-RECON-008", extra

        # 2. One side could not be decoded at all.
        for value in (log_value, phys_value):
            if isinstance(value, UndecodableValue):
                context["reason"] = value.reason
                return ReconResult.UNSUPPORTED, "R-RECON-007", extra

        # 3. Ambiguity is *why* there is no physical value, so it is reported
        #    ahead of "no physical value" - it is the more specific reason.
        if correlation.method.is_ambiguous:
            return ReconResult.UNRESOLVED, "R-RECON-012", extra

        # 4. A value read from a damaged tablespace cannot be relied on, so no
        #    difference can be attributed to anything.
        if damaged:
            context["integrity_status"] = integrity_status
            return ReconResult.UNRESOLVED, "R-RECON-009", extra

        # 5/6. Nothing to compare on one side. Which side it is, is the finding.
        if log_value is UNOBSERVED:
            return ReconResult.UNRESOLVED, "R-RECON-005", extra
        if phys_value is UNOBSERVED:
            return ReconResult.UNRESOLVED, "R-RECON-006", extra

        comparison = compare(log_value, phys_value, column, supported)

        # 7. Both observed, but not comparable without manufacturing a result.
        if not comparison.comparable:
            return ReconResult.UNSUPPORTED, "R-RECON-010", extra

        limited = history.gap_touched or column.name in history.partial_image_columns

        if comparison.equal:
            # 8. Agreement, qualified first by whether coverage lets us call it
            #    complete. This ordering matters: NULL agreeing under a gap is no
            #    more certain than any other agreement under that gap, so the
            #    coverage question is asked before the kind of value.
            if limited:
                return ReconResult.STRONG, "R-RECON-002", extra
            # 9. NULL on both sides is a real match: NULL is a value the database
            #    stored, not an absence of evidence.
            if log_value is None and phys_value is None:
                return ReconResult.EXACT, "R-RECON-011", extra
            return ReconResult.EXACT, "R-RECON-001", extra

        # 11. They differ, and everything hinges on whether missing evidence
        #     could account for it. This is Architecture.md section 5.14.
        if limited:
            return ReconResult.UNRESOLVED, "R-RECON-004", extra

        extra.extend(
            self._explain_conflict(history, correlation, column, phys_value, context, subject)
        )
        return ReconResult.CONFLICTING, "R-RECON-003", extra

    def _explain_conflict(
        self,
        history: RecordHistory,
        correlation: RecordCorrelation,
        column: Column,
        phys_value: Value,
        context: dict[str, str],
        subject: SubjectRef,
    ) -> list[Finding]:
        """Observations that sharpen a conflict without explaining it away.

        Neither draws a conclusion about how the value got there. They record
        what it coincides with and leave the interpretation to the examiner.
        """
        speculative = history.speculative_state.value(column.name)
        if speculative is not UNOBSERVED:
            result = compare(speculative, phys_value, column)
            if result.comparable and result.equal:
                transaction = (
                    correlation.transaction_ids[-1] if correlation.transaction_ids else ""
                )
                return [
                    self._finding(
                        "R-RECON-030", subject, {**context, "transaction": transaction}, ()
                    )
                ]

        produced = history.produced(column.name)
        if produced and not any(
            compare(value, phys_value, column).equal for value in produced
        ):
            return [self._finding("R-RECON-031", subject, context, ())]
        return []

    # ── Presence ─────────────────────────────────────────────────────────────

    def _presence_row(
        self,
        history: RecordHistory,
        correlation: RecordCorrelation,
        physical_values: dict[str, Value] | None,
        findings: list[Finding],
    ) -> FieldReconciliation:
        """Whether the record exists, asked before what it holds."""
        log_presence = history.final_log_state.presence
        if correlation.physical is None:
            phys_presence = Presence.UNKNOWN if physical_values is None else Presence.ABSENT
        else:
            phys_presence = (
                Presence.ABSENT if correlation.physical.is_deleted else Presence.PRESENT
            )

        subject = SubjectRef(SubjectKind.FIELD, f"{correlation.record.id}.presence")
        context = {
            "record": correlation.record.id,
            "presence": log_presence.value,
            "log_presence": log_presence.value,
            "phys_presence": phys_presence.value,
            "page_no": str(correlation.physical.page_no) if correlation.physical else "",
        }

        result, rule_id = self._classify_presence(
            log_presence, phys_presence, correlation, history
        )
        finding = self._finding(rule_id, subject, context, ())
        findings.append(finding)

        return FieldReconciliation(
            record_id=correlation.record.id,
            field=PRESENCE_FIELD,
            log=log_presence.value,
            phys=phys_presence.value,
            log_display=log_presence.value,
            phys_display=phys_presence.value,
            result=result,
            rule_id=rule_id,
            comparable=result in _COMPARED,
            provenance=self._field_provenance(history, correlation, PRESENCE_FIELD),
            findings=(finding,),
        )

    @staticmethod
    def _classify_presence(
        log_presence: Presence,
        phys_presence: Presence,
        correlation: RecordCorrelation,
        history: RecordHistory,
    ) -> tuple[ReconResult, str]:
        if correlation.method.is_ambiguous:
            return ReconResult.UNRESOLVED, "R-RECON-012"
        if Presence.UNKNOWN in (log_presence, phys_presence):
            return ReconResult.UNRESOLVED, "R-RECON-006"
        if log_presence is phys_presence:
            # A row flagged deleted on its page, with a logged deletion, is the
            # strongest agreement the evidence can offer about a removed row.
            if log_presence is Presence.ABSENT and correlation.physical is not None:
                return ReconResult.EXACT, "R-RECON-023"
            return ReconResult.EXACT, "R-RECON-020"
        if history.gap_touched:
            return ReconResult.UNRESOLVED, "R-RECON-022"
        return ReconResult.CONFLICTING, "R-RECON-021"

    # ── Roll-up ──────────────────────────────────────────────────────────────

    def _roll_up(
        self,
        record: RecordRef,
        fields: tuple[FieldReconciliation, ...],
        findings: list[Finding],
    ) -> RecordReconciliation:
        """R-ROLL-*. Descending severity, so the worst news is never hidden."""
        results = [f.result for f in fields]
        compared = [f for f in fields if f.comparable]

        if not results:
            rollup, rule_id = ReconResult.UNRESOLVED, "R-ROLL-005"
        elif all(r is ReconResult.UNSUPPORTED for r in results):
            rollup, rule_id = ReconResult.UNSUPPORTED, "R-ROLL-006"
        elif ReconResult.CONFLICTING in results:
            rollup, rule_id = ReconResult.CONFLICTING, "R-ROLL-001"
        elif ReconResult.UNRESOLVED in results or not compared:
            rollup, rule_id = ReconResult.UNRESOLVED, "R-ROLL-005"
        elif ReconResult.UNSUPPORTED in results:
            # Something was never examined, so the record cannot be called
            # agreeing - only partly compared.
            rollup, rule_id = ReconResult.PARTIAL, "R-ROLL-004"
        elif ReconResult.STRONG in results:
            rollup, rule_id = ReconResult.STRONG, "R-ROLL-003"
        else:
            rollup, rule_id = ReconResult.EXACT, "R-ROLL-002"

        label = self._label(fields)
        finding = self._finding(
            rule_id,
            SubjectRef(SubjectKind.RECORD, record.id),
            {
                "record": record.id,
                "count": str(len(compared) if compared else len(fields)),
                "total": str(len(fields)),
                "result": rollup.value,
                "label": label,
            },
            (),
        )
        findings.append(finding)

        return RecordReconciliation(
            record=record,
            fields=fields,
            rollup=rollup,
            rollup_rule_id=rule_id,
            rollup_label=label,
            triggers=tuple(
                (f.field, f.result)
                for f in fields
                if f.result in (ReconResult.CONFLICTING, ReconResult.UNRESOLVED)
            ),
            findings=(finding,),
        )

    @staticmethod
    def _label(fields: Sequence[FieldReconciliation]) -> str:
        """R-ROLL-007. Names the field when one carries the worst result.

        Reproduces the sample graphs exactly: "balance: Conflicting" for a single
        offender, "2 fields: Exact" when several share the top severity.
        """
        if not fields:
            return "no fields compared"
        worst = max((f.result for f in fields), key=lambda r: SEVERITY[r])
        at_worst = [f for f in fields if f.result is worst]
        if len(at_worst) == 1:
            return f"{at_worst[0].field}: {worst.value}"
        return f"{len(at_worst)} fields: {worst.value}"

    # ── Tables nothing could be correlated in ────────────────────────────────

    def _unsupported_table(
        self, table: UnsupportedTable, findings: list[Finding]
    ) -> RecordReconciliation:
        """One table-level row, so an uncorrelatable table is still reported.

        A table that silently produced no rows would read as a table with nothing
        wrong in it.
        """
        record = _table_ref(table)
        subject = SubjectRef(SubjectKind.TABLE, table.qualified_name)
        row_finding = self._finding(
            table.rule_id,
            subject,
            {"table": table.qualified_name, "record": table.qualified_name},
            (),
        )
        findings.append(row_finding)

        row = FieldReconciliation(
            record_id=record.id,
            field=PRESENCE_FIELD,
            log=UNOBSERVED,
            phys=UNOBSERVED,
            log_display=render(UNOBSERVED),
            phys_display=render(UNOBSERVED),
            result=ReconResult.UNSUPPORTED,
            rule_id=table.rule_id,
            comparable=False,
            findings=(row_finding,),
        )
        return self._roll_up(record, (row,), findings)

    # ── Physical lookup ──────────────────────────────────────────────────────

    def _physical_values(
        self, correlation: RecordCorrelation, schema: Schema | None
    ) -> dict[str, Value] | None:
        """The tablespace row's columns, or None when there is no counterpart.

        None means unobserved - we were not given the row - which is a different
        fact from the row being absent. The two must not collapse.
        """
        if correlation.physical is None or schema is None:
            return None
        key = correlation.record.to_key()
        for record in self._physical.records_for(key.database, key.table):
            if record.is_deleted != correlation.physical.is_deleted:
                continue
            if self._key_of(record, schema) == key:
                return dict(record.values)
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

    @staticmethod
    def _field_provenance(
        history: RecordHistory, correlation: RecordCorrelation, column: str
    ) -> FieldProvenance:
        ref = history.final_log_state.derived_from.get(column)
        narrowed = tuple(
            p for p in correlation.provenance if ref is not None and p.log_position == ref[1]
        )
        return FieldProvenance(
            log=narrowed or correlation.provenance,
            physical=correlation.physical.provenance if correlation.physical else None,
            transaction_id=(
                correlation.transaction_ids[-1] if correlation.transaction_ids else None
            ),
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


def _table_ref(table: UnsupportedTable) -> RecordRef:
    """A RecordRef standing for a whole table, for its single unsupported row."""
    return RecordRef(
        id=f"{table.table}:*",
        table=table.qualified_name,
        key="(no correlatable identity)",
        pk="*",
        label=f"{table.qualified_name} · whole table",
        database=table.database,
        key_columns=(),
        key_values=(),
    )
