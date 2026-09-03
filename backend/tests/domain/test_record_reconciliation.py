"""ReconciliationService: datasets ds02, ds08, ds09, ds10.

ds08 is the one that matters most. A log-derived value and a tablespace value
differ, and a binlog file is missing from the evidence set. The answer must be
Unresolved, never Conflicting - Architecture.md section 5.14 is the worked
example, and reporting a conflict there would present an evidence gap as
tampering.
"""

from __future__ import annotations

from decimal import Decimal

from core.domain.models.classification import ReconResult
from core.domain.models.reconciliation import PRESENCE_FIELD
from core.domain.models.values import UndecodableValue
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.record_reconciliation import ReconciliationService
from core.domain.services.state_reconstruction import StateReconstructionService
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.builders import (
    accounts_schema,
    col,
    ev,
    integrity,
    inventory,
    marker,
    phys,
    transfers_schema,
)
from tests.fixtures.inmemory import (
    InMemoryEventSource,
    InMemoryEvidenceContext,
    InMemoryPhysicalRecordSource,
    InMemorySchemaCatalog,
)

SINGLE_LOG = inventory("binlog.000018")
_DEFAULT = object()


def run(events, markers, *, records=(), schemas=None, inv=_DEFAULT, integrity_map=None):  # type: ignore[no-untyped-def]
    schemas = schemas or (accounts_schema(),)
    catalogue = InMemorySchemaCatalog(*schemas)
    evidence = InMemoryEvidenceContext(
        inventory=SINGLE_LOG if inv is _DEFAULT else inv,
        integrity=integrity_map,
        physical_tables=frozenset((s.database, s.table) for s in schemas),
    )
    source = InMemoryPhysicalRecordSource(*records)
    grouping = TransactionGroupingService(evidence).group(InMemoryEventSource(events, markers))
    correlation = RecordCorrelationService(catalogue, source, evidence).correlate(grouping)
    reconstruction = StateReconstructionService(catalogue, source, evidence).reconstruct(
        grouping, correlation
    )
    return ReconciliationService(catalogue, source, evidence).reconcile(
        reconstruction, correlation, grouping.coverage
    )


def committed(*positions: int, seq: int = 1):  # type: ignore[no-untyped-def]
    return marker("committed", 90, 9999, event_positions=positions, gtid_sequence=seq)


def field(result, record_id: str, name: str):  # type: ignore[no-untyped-def]
    return next(r for r in result.rows if r.record_id == record_id and r.field == name)


def rule_ids(result) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.rule_id for f in result.findings}


FULL_ROW = {"account_id": 101, "owner": "A", "balance": Decimal("4000.00"), "status": "active"}


# ── ds02: the finance golden case ────────────────────────────────────────────


def test_ds02_agreeing_record_is_exact_throughout() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": Decimal("5000.00")},
            after=FULL_ROW)],
        [committed(100, seq=1452)],
        records=[phys("accounts", FULL_ROW)],
    )

    record = result.record("accounts:101")
    assert record is not None
    assert record.rollup is ReconResult.EXACT
    assert record.rollup_label == "5 fields: Exact"
    assert not record.flagged
    assert all(r.result is ReconResult.EXACT for r in record.fields)


def test_ds02_presence_row_comes_first_for_every_record() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", FULL_ROW)],
    )
    assert result.rows[0].field == PRESENCE_FIELD


def test_ds02_a_differing_field_conflicts_when_coverage_is_complete() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("3500.00")})],
    )

    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.CONFLICTING
    assert balance.rule_id == "R-RECON-003"
    assert balance.log_display == "4000.00"
    assert balance.phys_display == "3500.00"

    record = result.record("accounts:101")
    assert record is not None
    assert record.rollup is ReconResult.CONFLICTING
    assert record.rollup_label == "balance: Conflicting"
    assert record.flagged


def test_ds02_a_physical_value_matching_a_rolled_back_one_is_reported_as_such() -> None:
    """An observation with provenance. The engine draws no conclusion from it."""
    result = run(
        [
            ev("UPDATE", 100, before={"account_id": 101, "balance": Decimal("5000.00")},
               after=FULL_ROW),
            ev("UPDATE", 200, before=FULL_ROW,
               after={**FULL_ROW, "balance": Decimal("3500.00")}),
        ],
        [
            committed(100, seq=1452),
            marker("rolled_back", 190, 210, event_positions=(200,), gtid_sequence=1449),
        ],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("3500.00")})],
    )

    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.CONFLICTING
    assert "R-RECON-030" in {f.rule_id for f in balance.findings}


def test_ds02_a_physical_value_no_event_produced_is_reported_as_such() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("999.00")})],
    )
    balance = field(result, "accounts:101", "balance")
    assert "R-RECON-031" in {f.rule_id for f in balance.findings}


def test_ds02_rollup_label_matches_the_sample_graphs() -> None:
    result = run(
        [ev("INSERT", 100, table="transfers",
            after={"transfer_id": 9001, "amount": Decimal("10"), "status": "done"})],
        [committed(100)],
        schemas=(transfers_schema(),),
        records=[phys("transfers", {"transfer_id": 9001, "amount": Decimal("10"),
                                    "status": "done"})],
    )
    record = result.record("transfers:9001")
    assert record is not None
    assert record.rollup_label == "4 fields: Exact"


# ── ds08: the gap must never read as a conflict ──────────────────────────────


def test_ds08_values_differing_across_a_missing_log_are_unresolved() -> None:
    """Architecture.md 5.14. The regression test that matters most in the suite."""
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": Decimal("5000.00")},
            after={**FULL_ROW, "balance": Decimal("4500.00")})],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("4000.00")})],
        inv=inventory("binlog.000018", "binlog.000019", missing=("binlog.000019",)),
    )

    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.UNRESOLVED
    assert balance.rule_id == "R-RECON-004"


def test_ds08_no_field_anywhere_is_conflicting_when_a_log_is_missing() -> None:
    """Asserted across the whole result, not just the field under test."""
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": Decimal("5000.00")},
            after={**FULL_ROW, "balance": Decimal("4500.00")})],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("4000.00")})],
        inv=inventory("binlog.000018", "binlog.000019", missing=("binlog.000019",)),
    )
    assert all(r.result is not ReconResult.CONFLICTING for r in result.rows)


def test_ds08_agreement_under_a_gap_is_strong_not_exact() -> None:
    """The values agree, but we cannot call the agreement complete."""
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", FULL_ROW)],
        inv=inventory("binlog.000018", "binlog.000019", missing=("binlog.000019",)),
    )
    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.STRONG
    assert balance.rule_id == "R-RECON-002"


def test_ds08_snapshot_timing_is_a_case_level_notice_only() -> None:
    """It must not downgrade individual comparisons, or a clean case collapses."""
    clean = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", FULL_ROW)],
    )
    assert "R-COV-005" not in rule_ids(clean)
    assert all(r.result is ReconResult.EXACT for r in clean.rows)


# ── ds09: unsupported and undecodable ────────────────────────────────────────


def test_ds09_undecodable_value_is_unsupported_not_conflicting() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101},
            after={**FULL_ROW, "owner": UndecodableValue("BLOB not supported")})],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "owner": "A"})],
    )

    owner = field(result, "accounts:101", "owner")
    assert owner.result is ReconResult.UNSUPPORTED
    assert owner.rule_id == "R-RECON-007"
    assert not owner.comparable


def test_ds09_a_column_type_outside_the_validated_scope_is_unsupported() -> None:
    schema = accounts_schema()
    widened = type(schema)(
        database=schema.database,
        table=schema.table,
        columns=(*schema.columns, col("location", 5, "POINT")),
        mysql_version_id=schema.mysql_version_id,
    )
    result = run(
        [ev("INSERT", 100, after={**FULL_ROW, "location": "x"})],
        [committed(100)],
        schemas=(widened,),
        records=[phys("accounts", {**FULL_ROW, "location": "x"})],
    )

    location = field(result, "accounts:101", "location")
    assert location.result is ReconResult.UNSUPPORTED
    assert location.rule_id == "R-RECON-008"


def test_ds09_an_unsupported_field_makes_the_record_partial_not_exact() -> None:
    """A field nobody examined cannot support a verdict of agreement."""
    schema = accounts_schema()
    widened = type(schema)(
        database=schema.database,
        table=schema.table,
        columns=(*schema.columns, col("location", 5, "POINT")),
        mysql_version_id=schema.mysql_version_id,
    )
    result = run(
        [ev("INSERT", 100, after={**FULL_ROW, "location": "x"})],
        [committed(100)],
        schemas=(widened,),
        records=[phys("accounts", {**FULL_ROW, "location": "x"})],
    )
    record = result.record("accounts:101")
    assert record is not None
    assert record.rollup is ReconResult.PARTIAL
    assert record.rollup_rule_id == "R-ROLL-004"


# ── ds10: damaged pages ──────────────────────────────────────────────────────


def test_ds10_a_damaged_tablespace_makes_every_comparison_unresolved() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("1.00")})],
        integrity_map={("finance", "accounts"): integrity("damaged", damaged_pages=3)},
    )

    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.UNRESOLVED
    assert balance.rule_id == "R-RECON-009"
    assert all(r.result is not ReconResult.CONFLICTING for r in result.rows)


def test_ds10_a_valid_tablespace_does_not_suppress_a_conflict() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("1.00")})],
        integrity_map={("finance", "accounts"): integrity("valid")},
    )
    assert field(result, "accounts:101", "balance").result is ReconResult.CONFLICTING


# ── Presence ─────────────────────────────────────────────────────────────────


def test_a_logged_deletion_matching_a_deleted_remnant_is_exact() -> None:
    result = run(
        [ev("DELETE", 100, before={"account_id": 102, "balance": Decimal("7500.00")})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 102, "balance": Decimal("7500.00")},
                      deleted=True)],
    )
    presence = field(result, "accounts:102", PRESENCE_FIELD)
    assert presence.result is ReconResult.EXACT
    assert presence.rule_id == "R-RECON-023"


def test_a_row_the_log_deleted_but_the_tablespace_still_holds_conflicts() -> None:
    result = run(
        [ev("DELETE", 100, before={"account_id": 101, "balance": Decimal("1.00")})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101, "balance": Decimal("1.00")})],
    )
    presence = field(result, "accounts:101", PRESENCE_FIELD)
    assert presence.result is ReconResult.CONFLICTING
    assert presence.rule_id == "R-RECON-021"


def test_the_same_presence_difference_under_a_gap_is_unresolved() -> None:
    result = run(
        [ev("DELETE", 100, before={"account_id": 101, "balance": Decimal("1.00")})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101, "balance": Decimal("1.00")})],
        inv=inventory("binlog.000018", "binlog.000019", missing=("binlog.000019",)),
    )
    presence = field(result, "accounts:101", PRESENCE_FIELD)
    assert presence.result is ReconResult.UNRESOLVED
    assert presence.rule_id == "R-RECON-022"


# ── Ambiguity and missing sides ──────────────────────────────────────────────


def test_an_ambiguous_correlation_makes_every_field_unresolved() -> None:
    """Ambiguity is reported ahead of "no physical value" - it is why there is none."""
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[
            phys("accounts", {**FULL_ROW, "balance": Decimal("1.00")}, page_offset=170),
            phys("accounts", {**FULL_ROW, "balance": Decimal("2.00")}, page_offset=220),
        ],
    )

    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.UNRESOLVED
    assert balance.rule_id == "R-RECON-012"


def test_a_log_only_record_is_unresolved_on_the_physical_side() -> None:
    result = run(
        [ev("INSERT", 100, after=FULL_ROW)],
        [committed(100)],
        records=[],
    )
    balance = field(result, "accounts:101", "balance")
    assert balance.result is ReconResult.UNRESOLVED
    assert balance.rule_id == "R-RECON-006"


def test_a_column_no_event_mentioned_is_unresolved_on_the_log_side() -> None:
    result = run(
        [ev("INSERT", 100, after={"account_id": 101, "balance": Decimal("4000.00")})],
        [committed(100)],
        records=[phys("accounts", FULL_ROW)],
    )
    owner = field(result, "accounts:101", "owner")
    assert owner.result is ReconResult.UNRESOLVED
    assert owner.rule_id == "R-RECON-005"


def test_null_on_both_sides_is_a_real_match() -> None:
    result = run(
        [ev("INSERT", 100, after={**FULL_ROW, "owner": None})],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "owner": None})],
    )
    owner = field(result, "accounts:101", "owner")
    assert owner.result is ReconResult.EXACT
    assert owner.rule_id == "R-RECON-011"
    assert owner.log_display == "NULL"


# ── Unsupported tables ───────────────────────────────────────────────────────


def test_a_table_with_no_primary_key_still_produces_one_row() -> None:
    """A table that silently produced nothing would read as a table with no issues."""
    no_pk = type(accounts_schema())(
        database="finance",
        table="audit_log",
        columns=(col("message", 1, "varchar"),),
        mysql_version_id=80410,
    )
    result = run(
        [ev("INSERT", 100, table="audit_log", after={"message": "x"})],
        [committed(100)],
        schemas=(no_pk,),
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.rollup is ReconResult.UNSUPPORTED
    assert record.rollup_rule_id == "R-ROLL-006"
    assert record.record.table == "finance.audit_log"


# ── Cross-cutting ────────────────────────────────────────────────────────────


def test_rows_are_flattened_in_record_order() -> None:
    result = run(
        [
            ev("INSERT", 100, table="transfers",
               after={"transfer_id": 9002, "amount": Decimal("1"), "status": "x"}),
            ev("INSERT", 110, after=FULL_ROW),
        ],
        [committed(100, 110)],
        schemas=(accounts_schema(), transfers_schema()),
        records=[phys("accounts", FULL_ROW)],
    )
    seen = [r.record_id for r in result.rows]
    assert seen.index("accounts:101") < seen.index("transfers:9002")


def test_counts_tally_every_row() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", FULL_ROW)],
    )
    assert sum(result.counts.values()) == len(result.rows)


def test_every_row_carries_a_rule_id_from_the_catalogue() -> None:
    result = run(
        [ev("UPDATE", 100, before={"account_id": 101}, after=FULL_ROW)],
        [committed(100)],
        records=[phys("accounts", {**FULL_ROW, "balance": Decimal("1.00")})],
    )
    for row in result.rows:
        assert row.rule_id.startswith("R-")
