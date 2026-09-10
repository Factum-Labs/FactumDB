"""RecordCorrelationService: datasets ds06, ds07, ds11.

Composite keys, primary-key updates, and tables with no primary key at all.

The primary-key-update cases carry the weight here. Following a key change is
what lets one row stay one record across its whole history, but following it too
eagerly merges two records the evidence never said were the same. Those tests
assert both halves: the unambiguous chain is followed, the ambiguous one is not.
"""

from __future__ import annotations

from core.domain.models.canonical import Schema
from core.domain.models.correlation import MatchMethod
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.builders import (
    accounts_schema,
    col,
    ev,
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

ORDER_LINES = Schema(
    database="finance",
    table="order_lines",
    columns=(
        col("order_id", 1, "int", pk=True, nullable=False),
        col("line_no", 2, "int", pk=True, nullable=False),
        col("qty", 3, "int"),
    ),
    mysql_version_id=80410,
)

NO_PK = Schema(
    database="finance",
    table="audit_log",
    columns=(col("message", 1, "varchar"), col("at", 2, "datetime")),
    mysql_version_id=80410,
)


def correlate(events, markers, *, schemas=(), records=(), physical_tables=None):  # type: ignore[no-untyped-def]
    catalogue = InMemorySchemaCatalog(*(schemas or (accounts_schema(),)))
    tables = (
        physical_tables
        if physical_tables is not None
        else frozenset((s.database, s.table) for s in (schemas or (accounts_schema(),)))
    )
    evidence = InMemoryEvidenceContext(inventory=SINGLE_LOG, physical_tables=tables)
    grouping = TransactionGroupingService(evidence).group(InMemoryEventSource(events, markers))
    service = RecordCorrelationService(
        catalogue, InMemoryPhysicalRecordSource(*records), evidence
    )
    return service.correlate(grouping)


def rule_ids(result) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.rule_id for f in result.findings}


def committed(*positions: int, start: int = 90, end: int = 999, seq: int = 1):  # type: ignore[no-untyped-def]
    return marker("committed", start, end, event_positions=positions, gtid_sequence=seq)


# ── Baseline: single-column primary key ──────────────────────────────────────


def test_single_column_key_matches_exactly() -> None:
    result = correlate(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
            after={"account_id": 101, "balance": 4000})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101, "balance": 4000})],
    )

    assert [r.record.id for r in result.records] == ["accounts:101"]
    correlation = result.records[0]
    assert correlation.method is MatchMethod.PK_EXACT
    assert correlation.record.key == "account_id = 101"
    assert correlation.record.label == "finance.accounts · 101"
    assert correlation.has_physical_evidence


def test_delete_takes_its_identity_from_the_before_image() -> None:
    """A DELETE has no after-image, so its identity can only come from before."""
    result = correlate(
        [ev("DELETE", 100, before={"account_id": 102, "balance": 7500})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 102}, deleted=True)],
    )
    assert [r.record.id for r in result.records] == ["accounts:102"]
    assert result.records[0].physical is not None
    assert result.records[0].physical.is_deleted


def test_edges_dedupe_but_keep_every_contributing_event() -> None:
    """Two updates in one transaction are one edge - traceable to both events."""
    result = correlate(
        [
            ev("UPDATE", 100, after={"account_id": 101}),
            ev("UPDATE", 110, after={"account_id": 101}),
        ],
        [committed(100, 110)],
        records=[phys("accounts", {"account_id": 101})],
    )

    assert len(result.edges) == 1
    edge = result.edges[0]
    assert (edge.tx_id, edge.record_id, edge.event_type) == ("TX-1", "accounts:101", "UPDATE")
    assert len(edge.event_refs) == 2


# ── ds06: composite primary key ──────────────────────────────────────────────


def test_ds06_composite_key_renders_and_matches() -> None:
    result = correlate(
        [ev("UPDATE", 100, table="order_lines",
            before={"order_id": 5001, "line_no": 2, "qty": 1},
            after={"order_id": 5001, "line_no": 2, "qty": 3})],
        [committed(100)],
        schemas=(ORDER_LINES,),
        records=[phys("order_lines", {"order_id": 5001, "line_no": 2, "qty": 3})],
    )

    correlation = result.records[0]
    assert correlation.record.id == "order_lines:5001|2"
    assert correlation.record.key == "order_id = 5001, line_no = 2"
    assert correlation.record.pk == "5001|2"
    assert correlation.method is MatchMethod.COMPOSITE_PK_EXACT
    assert correlation.has_physical_evidence


def test_ds06_composite_key_components_follow_schema_position_order() -> None:
    """Rendered in the other order it would read as a different record."""
    result = correlate(
        [ev("INSERT", 100, table="order_lines",
            after={"line_no": 2, "order_id": 5001, "qty": 3})],
        [committed(100)],
        schemas=(ORDER_LINES,),
    )
    assert result.records[0].record.key_columns == ("order_id", "line_no")
    assert result.records[0].record.pk == "5001|2"


def test_ds06_a_key_value_containing_the_separator_is_reported() -> None:
    """"a|b" as one value and ("a","b") as two render identically."""
    schema = Schema(
        database="finance",
        table="tags",
        columns=(col("tag", 1, "varchar", pk=True, nullable=False),),
        mysql_version_id=80410,
    )
    result = correlate(
        [ev("INSERT", 100, table="tags", after={"tag": "red|blue"})],
        [committed(100)],
        schemas=(schema,),
    )
    assert "R-ID-002" in rule_ids(result)


# ── ds07: primary key updates ────────────────────────────────────────────────


def test_ds07_unambiguous_key_change_stays_one_record() -> None:
    """101 -> 111, then a further update on 111. One row throughout."""
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
               after={"account_id": 111, "balance": 5000}),
            ev("UPDATE", 110, before={"account_id": 111, "balance": 5000},
               after={"account_id": 111, "balance": 4000}),
        ],
        [committed(100, 110)],
        records=[phys("accounts", {"account_id": 111, "balance": 4000})],
    )

    assert [r.record.id for r in result.records] == ["accounts:111"]
    correlation = result.records[0]
    assert correlation.method is MatchMethod.PK_UPDATE_CONTINUITY
    assert [a.id for a in correlation.identity_aliases] == ["accounts:101"]
    assert len(correlation.log_event_refs) == 2
    assert "R-CORR-010" in rule_ids(result)


def test_ds07_canonical_identity_is_the_latest_key_per_adr_02() -> None:
    """The tablespace holds the current key, so the match is direct."""
    result = correlate(
        [ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 111})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 111})],
    )
    correlation = result.records[0]
    assert correlation.record.id == "accounts:111"
    assert correlation.has_physical_evidence


def test_ds07_two_keys_merging_into_one_is_refused() -> None:
    """101 -> 111 and 102 -> 111. Merging would assert 101 and 102 are one row."""
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 111}),
            ev("UPDATE", 110, before={"account_id": 102}, after={"account_id": 111}),
        ],
        [committed(100, 110)],
    )

    assert "R-CORR-011" in rule_ids(result)
    # The identities stay separate rather than being collapsed into one.
    assert all(r.method is not MatchMethod.PK_UPDATE_CONTINUITY for r in result.records)
    assert all(r.identity_aliases == () for r in result.records)


def test_ds07_refusing_continuity_does_not_discard_the_old_keys() -> None:
    """The before-images observed rows 101 and 102. They must not vanish.

    Refusing to merge identities is the right call, but if the old keys then
    appear nowhere the report has silently dropped two observations the evidence
    actually made. Each key gets its own record, and the update appears under
    both identities - which is the honest reading when the evidence does not say
    they are the same row.
    """
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 111}),
            ev("UPDATE", 110, before={"account_id": 102}, after={"account_id": 111}),
        ],
        [committed(100, 110)],
    )

    assert [r.record.id for r in result.records] == [
        "accounts:101",
        "accounts:102",
        "accounts:111",
    ]
    # The event at 100 is evidence about both the key it left and the key it made.
    assert result.record("accounts:101").log_event_refs == (("binlog.000018", 100),)
    assert result.record("accounts:111").log_event_refs == (
        ("binlog.000018", 100),
        ("binlog.000018", 110),
    )


def test_ds07_accepted_continuity_does_not_duplicate_the_record() -> None:
    """The mirror of the test above: when the chain holds, there is one record.

    Guards against fixing the dropped-observation bug by always emitting the
    before-image key, which would split every ordinary key update in two.
    """
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 111}),
            ev("UPDATE", 110, before={"account_id": 111}, after={"account_id": 111}),
        ],
        [committed(100, 110)],
        records=[phys("accounts", {"account_id": 111})],
    )

    assert [r.record.id for r in result.records] == ["accounts:111"]
    correlation = result.records[0]
    assert [a.id for a in correlation.identity_aliases] == ["accounts:101"]
    assert correlation.method is MatchMethod.PK_UPDATE_CONTINUITY


def test_an_ordinary_update_never_splits_into_two_records() -> None:
    """The key did not change, so there is nothing to alias and nothing to split."""
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
               after={"account_id": 101, "balance": 4000}),
        ],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101, "balance": 4000})],
    )

    assert [r.record.id for r in result.records] == ["accounts:101"]
    assert result.records[0].identity_aliases == ()
    assert result.records[0].method is MatchMethod.PK_EXACT


def test_ds07_one_key_with_two_successors_is_refused() -> None:
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 111}),
            ev("UPDATE", 110, before={"account_id": 101}, after={"account_id": 121}),
        ],
        [committed(100, 110)],
    )
    assert "R-CORR-011" in rule_ids(result)
    assert all(r.identity_aliases == () for r in result.records)


def test_ds07_cyclic_key_changes_are_refused() -> None:
    """101 -> 111 -> 101 has no defensible terminal key."""
    result = correlate(
        [
            ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 111}),
            ev("UPDATE", 110, before={"account_id": 111}, after={"account_id": 101}),
        ],
        [committed(100, 110)],
    )
    assert "R-CORR-011" in rule_ids(result)


def test_ds07_key_reused_after_delete_is_still_one_record() -> None:
    result = correlate(
        [
            ev("DELETE", 100, before={"account_id": 101, "balance": 5000}),
            ev("INSERT", 110, after={"account_id": 101, "balance": 200}),
        ],
        [committed(100, 110)],
        records=[phys("accounts", {"account_id": 101, "balance": 200})],
    )

    assert [r.record.id for r in result.records] == ["accounts:101"]
    assert "R-CORR-012" in rule_ids(result)


# ── ds11: no primary key ─────────────────────────────────────────────────────


def test_ds11_table_without_a_primary_key_produces_no_record() -> None:
    """InnoDB's hidden row id is invisible to mysqlbinlog, so there is no identity.

    Synthesising one would be fabricating identity, so the events correlate to
    nothing and the table is reported unsupported.
    """
    result = correlate(
        [ev("INSERT", 100, table="audit_log", after={"message": "x"})],
        [committed(100)],
        schemas=(NO_PK,),
    )

    assert result.records == ()
    assert [u.qualified_name for u in result.unsupported_tables] == ["finance.audit_log"]
    assert result.unsupported_tables[0].rule_id == "R-CORR-020"
    assert "R-CORR-020" in rule_ids(result)
    assert result.event_correlations[0].method is MatchMethod.UNSUPPORTED_NO_PK
    assert result.event_correlations[0].record_id is None


def test_ds11_missing_schema_is_reported_separately_from_missing_key() -> None:
    """Two different defects; a report must not conflate them."""
    result = correlate(
        [ev("INSERT", 100, table="unknown_table", after={"x": 1})],
        [committed(100)],
        schemas=(accounts_schema(),),
        physical_tables=frozenset({("finance", "accounts")}),
    )
    assert "R-CORR-021" in rule_ids(result)
    assert result.event_correlations[0].method is MatchMethod.UNSUPPORTED_NO_SCHEMA


# ── Physical side ────────────────────────────────────────────────────────────


def test_two_live_rows_at_one_key_make_the_correlation_ambiguous() -> None:
    """Neither is chosen. Picking arbitrarily would fabricate a comparison."""
    result = correlate(
        [ev("UPDATE", 100, after={"account_id": 101})],
        [committed(100)],
        records=[
            phys("accounts", {"account_id": 101, "balance": 1}, page_offset=170),
            phys("accounts", {"account_id": 101, "balance": 2}, page_offset=220),
        ],
    )

    correlation = result.records[0]
    assert correlation.method is MatchMethod.AMBIGUOUS
    assert correlation.physical is None
    assert len(correlation.physical_candidates) == 2
    assert "R-CORR-022" in rule_ids(result)


def test_a_deleted_remnant_beside_a_live_row_is_kept_but_not_chosen() -> None:
    result = correlate(
        [ev("UPDATE", 100, after={"account_id": 101})],
        [committed(100)],
        records=[
            phys("accounts", {"account_id": 101, "balance": 1}, deleted=True),
            phys("accounts", {"account_id": 101, "balance": 2}),
        ],
    )

    correlation = result.records[0]
    assert correlation.physical is not None
    assert not correlation.physical.is_deleted
    assert len(correlation.physical_candidates) == 2
    assert "R-CORR-023" in rule_ids(result)


def test_a_record_with_no_physical_counterpart_is_log_only() -> None:
    result = correlate(
        [ev("INSERT", 100, after={"account_id": 999})],
        [committed(100)],
        records=[],
    )
    assert result.records[0].method is MatchMethod.LOG_ONLY
    assert result.records[0].physical is None


def test_a_physical_row_with_no_events_is_still_a_record() -> None:
    """This is what produces the accounts:310 node in the sample graph."""
    result = correlate(
        [ev("UPDATE", 100, after={"account_id": 101})],
        [committed(100)],
        records=[
            phys("accounts", {"account_id": 101}),
            phys("accounts", {"account_id": 310, "balance": 900}),
        ],
    )

    by_id = {r.record.id: r for r in result.records}
    assert by_id["accounts:310"].method is MatchMethod.PHYSICAL_ONLY
    assert by_id["accounts:310"].log_event_refs == ()
    assert "R-CORR-031" in rule_ids(result)


def test_a_table_with_no_tablespace_is_unobserved_not_missing() -> None:
    """"We were not given the file" must never read as "the row is not there"."""
    result = correlate(
        [ev("INSERT", 100, table="transfers", after={"transfer_id": 9001})],
        [committed(100)],
        schemas=(transfers_schema(),),
        physical_tables=frozenset(),
    )

    assert result.records[0].method is MatchMethod.LOG_ONLY
    assert result.records[0].physical is None
    assert "R-CORR-030" in rule_ids(result)


def test_physical_location_is_carried_for_hex_verification() -> None:
    result = correlate(
        [ev("UPDATE", 100, after={"account_id": 101})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101}, page_no=4, page_offset=170)],
    )
    assert result.records[0].physical is not None
    assert result.records[0].physical.location == "page 4 offset 170"


# ── Cross-cutting ────────────────────────────────────────────────────────────


def test_records_are_sorted_canonically() -> None:
    result = correlate(
        [
            ev("INSERT", 100, table="transfers", after={"transfer_id": 9002}),
            ev("INSERT", 110, after={"account_id": 205}),
            ev("INSERT", 120, after={"account_id": 101}),
        ],
        [committed(100, 110, 120)],
        schemas=(accounts_schema(), transfers_schema()),
    )
    assert [r.record.id for r in result.records] == [
        "accounts:101",
        "accounts:205",
        "transfers:9002",
    ]


def test_same_table_name_in_two_databases_is_reported_as_colliding() -> None:
    result = correlate(
        [
            ev("INSERT", 100, database="finance", after={"account_id": 101}),
            ev("INSERT", 110, database="hr", after={"account_id": 101}),
        ],
        [committed(100, 110)],
        schemas=(accounts_schema("finance"), accounts_schema("hr")),
    )
    assert "R-ID-003" in rule_ids(result)


def test_ungrouped_events_are_still_correlated() -> None:
    """An unobserved transaction is a separate gap from the record's identity."""
    result = correlate(
        [ev("UPDATE", 500, after={"account_id": 101})],
        [committed(100, start=90, end=110)],
        records=[phys("accounts", {"account_id": 101})],
    )
    assert [r.record.id for r in result.records] == ["accounts:101"]
    assert result.records[0].log_event_refs == (("binlog.000018", 500),)


def test_correlation_is_repeatable_under_input_reordering() -> None:
    events = [
        ev("INSERT", 120, after={"account_id": 101}),
        ev("INSERT", 100, table="transfers", after={"transfer_id": 9001}),
        ev("INSERT", 110, after={"account_id": 205}),
    ]
    schemas = (accounts_schema(), transfers_schema())
    first = correlate(events, [committed(100, 110, 120)], schemas=schemas)
    second = correlate(list(reversed(events)), [committed(100, 110, 120)], schemas=schemas)

    assert [r.record.id for r in first.records] == [r.record.id for r in second.records]
    assert first.edges == second.edges
