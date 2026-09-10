"""TransactionGroupingService: datasets ds01-ds05.

The scenarios map onto the week 7 evaluation list: single-row CRUD, a multi-table
committed transaction, a rolled-back one, an incomplete one, and interleaved
concurrent sessions.

The interleaving cases carry the most weight. A grouping service that assumes the
log is sequential produces confident, plausible, wrong answers - it attributes one
session's changes to another's transaction - so those tests assert the service
refuses rather than guesses.
"""

from __future__ import annotations

from core.domain.models.transactions import IncompletenessReason, TransactionStatus
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.builders import ev, inventory, marker
from tests.fixtures.inmemory import InMemoryEventSource, InMemoryEvidenceContext

#: The default evidence set: one log, listed and present. Scenarios that are
#: about coverage pass their own.
SINGLE_LOG = inventory("binlog.000018")

#: Sentinel so `inv=None` can mean "no index was provided", which is a real and
#: consequential case, rather than "use the default".
_DEFAULT = object()


def group(events, markers, *, inv=_DEFAULT):  # type: ignore[no-untyped-def]
    resolved = SINGLE_LOG if inv is _DEFAULT else inv
    service = TransactionGroupingService(InMemoryEvidenceContext(inventory=resolved))
    return service.group(InMemoryEventSource(events, markers))


def rule_ids(result) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.rule_id for f in result.findings}


# ── ds01: single-row insert, update, delete ──────────────────────────────────


def test_ds01_single_row_lifecycle_groups_into_three_transactions() -> None:
    events = [
        ev("INSERT", 100, after={"account_id": 101, "balance": 5000}),
        ev("UPDATE", 200, before={"account_id": 101, "balance": 5000},
           after={"account_id": 101, "balance": 4000}),
        ev("DELETE", 300, before={"account_id": 101, "balance": 4000}),
    ]
    markers = [
        marker("committed", 90, 110, event_positions=(100,), gtid_sequence=1, xid=10),
        marker("committed", 190, 210, event_positions=(200,), gtid_sequence=2, xid=11),
        marker("committed", 290, 310, event_positions=(300,), gtid_sequence=3, xid=12),
    ]
    result = group(events, markers)

    assert [t.id for t in result.transactions] == ["TX-1", "TX-2", "TX-3"]
    assert all(t.status is TransactionStatus.COMMITTED for t in result.transactions)
    assert all(t.durable for t in result.transactions)
    assert result.ungrouped_events == ()
    assert result.event_count == 3
    assert result.coverage.complete


def test_ds01_event_order_is_assigned_within_each_transaction() -> None:
    events = [
        ev("INSERT", 120, table="transfers", after={"transfer_id": 9001}),
        ev("INSERT", 100, after={"account_id": 101}),
    ]
    markers = [marker("committed", 90, 130, event_positions=(100, 120), gtid_sequence=1)]
    result = group(events, markers)

    transaction = result.transactions[0]
    assert [g.order for g in transaction.events] == [0, 1]
    # Ordered by log position, not by the order the adapter happened to emit them.
    assert [g.event.log_position for g in transaction.events] == [100, 120]


# ── ds02: multi-table committed transaction ──────────────────────────────────


def test_ds02_multi_table_transaction_reports_every_table_touched() -> None:
    events = [
        ev("UPDATE", 100, after={"account_id": 101}),
        ev("UPDATE", 110, after={"account_id": 205}),
        ev("INSERT", 120, table="transfers", after={"transfer_id": 9001}),
    ]
    markers = [
        marker("committed", 90, 130, event_positions=(100, 110, 120), gtid_sequence=1452, xid=8821)
    ]
    result = group(events, markers)
    transaction = result.transactions[0]

    assert transaction.id == "TX-1452"
    assert transaction.tables_touched == ("finance.accounts", "finance.transfers")
    assert transaction.summary_counts == {"INSERT": 1, "UPDATE": 2}
    assert transaction.commit_position == 130
    assert transaction.xid == 8821


def test_ds02_transaction_ids_derive_from_evidence_not_a_counter() -> None:
    """Re-running over the same evidence must produce the same ids."""
    events = [ev("UPDATE", 100, after={"account_id": 101})]
    markers = [marker("committed", 90, 130, event_positions=(100,), gtid_sequence=1452)]

    first = group(events, markers)
    second = group(list(reversed(events)), markers)
    assert [t.id for t in first.transactions] == [t.id for t in second.transactions]


def test_ds02_two_server_uuids_force_qualified_ids() -> None:
    """A GTID sequence number is only unique within one server UUID."""
    events = [ev("UPDATE", 100), ev("UPDATE", 200)]
    markers = [
        marker("committed", 90, 110, event_positions=(100,), gtid="aaaaaaaa-0000:7"),
        marker("committed", 190, 210, event_positions=(200,), gtid="bbbbbbbb-0000:7"),
    ]
    result = group(events, markers)

    ids = [t.id for t in result.transactions]
    assert ids == ["TX-aaaaaaaa-7", "TX-bbbbbbbb-7"]
    assert len(set(ids)) == 2


# ── ds03: rolled back ────────────────────────────────────────────────────────


def test_ds03_rolled_back_transaction_is_kept_but_not_durable() -> None:
    """Rolled-back events are evidence. They are just never applied."""
    events = [ev("UPDATE", 2210, before={"account_id": 101, "balance": 4000},
                after={"account_id": 101, "balance": 3500})]
    markers = [marker("rolled_back", 2200, 2220, event_positions=(2210,), gtid_sequence=1449)]
    result = group(events, markers)

    transaction = result.transactions[0]
    assert transaction.status is TransactionStatus.ROLLED_BACK
    assert not transaction.durable
    assert len(transaction.events) == 1
    assert "R-GRP-003" in rule_ids(result)


# ── ds04: incomplete, and why ────────────────────────────────────────────────


def test_ds04_unterminated_at_end_of_log_is_unbounded() -> None:
    events = [ev("UPDATE", 1180, after={"account_id": 310})]
    markers = [marker("incomplete", 1170, 1190, event_positions=(1180,), gtid_sequence=1448)]
    result = group(events, markers)

    transaction = result.transactions[0]
    assert transaction.status is TransactionStatus.INCOMPLETE
    assert transaction.incompleteness_reason is IncompletenessReason.NO_TERMINATOR_IN_RANGE
    assert not transaction.durable
    assert "R-GRP-004" in rule_ids(result)
    assert "R-COV-003" in rule_ids(result)


def test_ds04_missing_file_in_sequence_is_bounded() -> None:
    """The index names the file that would resolve it, so the claim is stronger."""
    events = [ev("UPDATE", 8814, after={"account_id": 101})]
    markers = [marker("incomplete", 8800, 8820, event_positions=(8814,), gtid_sequence=1450)]
    inv = inventory(
        "binlog.000018", "binlog.000019", "binlog.000020", missing=("binlog.000019",)
    )
    result = group(events, markers, inv=inv)

    transaction = result.transactions[0]
    assert transaction.incompleteness_reason is IncompletenessReason.LOG_FILE_MISSING_IN_SEQUENCE
    assert "R-GRP-014" in rule_ids(result)
    assert "R-COV-002" in rule_ids(result)


def test_ds04_no_index_falls_back_to_the_unbounded_reason() -> None:
    """Without an index a missing file cannot be proved, so it is not claimed.

    This is the gap the catalogue review flagged: the reason must be cited, not
    left to an inferred default.
    """
    events = [ev("UPDATE", 8814, after={"account_id": 101})]
    markers = [marker("incomplete", 8800, 8820, event_positions=(8814,), gtid_sequence=1450)]
    result = group(events, markers, inv=None)

    transaction = result.transactions[0]
    assert transaction.incompleteness_reason is IncompletenessReason.NO_TERMINATOR_IN_RANGE
    assert "R-COV-001" in rule_ids(result)
    assert not result.coverage.complete


def test_ds04_marker_claiming_nothing_says_so_specifically() -> None:
    markers = [marker("incomplete", 8800, 8820, event_positions=(8814,), gtid_sequence=1450)]
    result = group([], markers)

    transaction = result.transactions[0]
    assert transaction.incompleteness_reason is IncompletenessReason.MARKER_WITHOUT_EVENTS
    assert "R-GRP-006" in rule_ids(result)
    assert "R-GRP-009" in rule_ids(result)


def test_ds04_absence_of_an_index_is_never_read_as_completeness() -> None:
    result = group([ev("UPDATE", 100)], [marker("committed", 90, 110, event_positions=(100,))],
                   inv=None)
    assert not result.coverage.complete
    assert [w.reason for w in result.coverage.gaps] == ["no_index"]


# ── ds05: interleaved concurrent sessions ────────────────────────────────────


def test_ds05_interleaved_sessions_claim_only_their_own_events() -> None:
    """Events from two threads interleave by position. Neither may steal the other's."""
    events = [
        ev("UPDATE", 100, thread_id=13, after={"account_id": 101}),
        ev("UPDATE", 110, thread_id=27, after={"account_id": 205}),
        ev("UPDATE", 120, thread_id=13, after={"account_id": 102}),
        ev("UPDATE", 130, thread_id=27, after={"account_id": 206}),
    ]
    markers = [
        marker("committed", 90, 125, event_positions=(100, 120), thread_id=13, gtid_sequence=1),
        marker("committed", 105, 135, event_positions=(110, 130), thread_id=27, gtid_sequence=2),
    ]
    result = group(events, markers)

    by_id = {t.id: t for t in result.transactions}
    assert [g.event.log_position for g in by_id["TX-1"].events] == [100, 120]
    assert [g.event.log_position for g in by_id["TX-2"].events] == [110, 130]
    assert result.ungrouped_events == ()


def test_ds05_overlapping_events_not_listed_by_the_marker_are_reported_not_claimed() -> None:
    events = [
        ev("UPDATE", 100, thread_id=13),
        ev("UPDATE", 110, thread_id=27),  # inside TX-1's range, not listed by it
    ]
    markers = [
        marker("committed", 90, 125, event_positions=(100,), thread_id=13, gtid_sequence=1),
    ]
    result = group(events, markers)

    transaction = result.transactions[0]
    assert [g.event.log_position for g in transaction.events] == [100]
    assert "R-GRP-010" in rule_ids(result)
    # The unlisted event is still evidence, just not this transaction's.
    assert [u.ref[1] for u in result.ungrouped_events] == [110]


def test_ds05_without_session_ids_the_service_refuses_to_group() -> None:
    """The heart of "never assume sequential".

    A marker with no event positions and no thread id surrounds two events. The
    tempting answer is to claim them by adjacency. The service refuses, because a
    confident wrong grouping attributes one session's changes to another.
    """
    events = [
        ev("UPDATE", 100, thread_id=None),
        ev("UPDATE", 110, thread_id=None),
    ]
    markers = [marker("incomplete", 90, 120, thread_id=None, gtid_sequence=1)]
    result = group(events, markers)

    transaction = result.transactions[0]
    assert transaction.events == ()
    assert transaction.incompleteness_reason is IncompletenessReason.MARKER_WITHOUT_EVENTS
    assert "R-GRP-008" in rule_ids(result)
    assert {u.ref[1] for u in result.ungrouped_events} == {100, 110}
    assert all(u.rule_id == "R-GRP-011" for u in result.ungrouped_events)


def test_ds05_session_fallback_works_when_thread_ids_are_present() -> None:
    """With session ids available the same shape groups cleanly."""
    events = [
        ev("UPDATE", 100, thread_id=13),
        ev("UPDATE", 110, thread_id=27),
    ]
    markers = [marker("committed", 90, 120, thread_id=13, gtid_sequence=1)]
    result = group(events, markers)

    assert [g.event.log_position for g in result.transactions[0].events] == [100]
    assert [u.ref[1] for u in result.ungrouped_events] == [110]


def test_ds05_session_key_prefers_gtid_then_thread() -> None:
    events = [ev("UPDATE", 100, thread_id=13)]
    with_gtid = group(events, [marker("committed", 90, 110, event_positions=(100,),
                                      gtid_sequence=5)])
    assert with_gtid.transactions[0].session_key.endswith(":5")

    without = group(events, [marker("committed", 90, 110, event_positions=(100,), thread_id=13)])
    assert without.transactions[0].session_key == "binlog.000018:13"


# ── Unclaimed events: the R-GRP-005 / R-GRP-011 boundary ─────────────────────


def test_leading_run_before_every_marker_becomes_one_synthesised_region() -> None:
    """Nothing precedes these events, so the log demonstrably begins mid-transaction."""
    events = [
        ev("UPDATE", 40),
        ev("UPDATE", 50),
        ev("INSERT", 200),
    ]
    markers = [marker("committed", 190, 210, event_positions=(200,), gtid_sequence=1)]
    result = group(events, markers)

    synthesised = [t for t in result.transactions if t.synthesised]
    assert len(synthesised) == 1
    region = synthesised[0]
    assert [g.event.log_position for g in region.events] == [40, 50]
    assert region.incompleteness_reason is IncompletenessReason.EVENTS_WITHOUT_BEGIN
    assert not region.durable
    assert "R-GRP-005" in rule_ids(result)


def test_a_synthesised_region_is_not_a_claim_of_one_transaction() -> None:
    """It is flagged so nothing downstream mistakes it for an observed transaction."""
    result = group([ev("UPDATE", 40)], [marker("committed", 190, 210, event_positions=(200,))])
    region = result.transactions[0]
    assert region.synthesised
    assert region.id.startswith("TX-SYNTH-")


def test_mid_stream_orphans_are_grouped_with_nothing() -> None:
    """Markers exist before them, so there is no evidence they belong together."""
    events = [
        ev("INSERT", 100),
        ev("UPDATE", 500),  # after the marker, claimed by nothing
        ev("UPDATE", 600),
    ]
    markers = [marker("committed", 90, 110, event_positions=(100,), gtid_sequence=1)]
    result = group(events, markers)

    assert not any(t.synthesised for t in result.transactions)
    assert {u.ref[1] for u in result.ungrouped_events} == {500, 600}
    assert "R-GRP-005" not in rule_ids(result)
    assert "R-GRP-011" in rule_ids(result)


def test_the_two_unclaimed_rules_never_both_fire_for_one_event() -> None:
    events = [ev("UPDATE", 40), ev("INSERT", 100), ev("UPDATE", 500)]
    markers = [marker("committed", 90, 110, event_positions=(100,), gtid_sequence=1)]
    result = group(events, markers)

    synthesised_refs = {
        g.ref for t in result.transactions if t.synthesised for g in t.events
    }
    orphan_refs = {u.ref for u in result.ungrouped_events}
    assert synthesised_refs & orphan_refs == set()
    assert synthesised_refs == {("binlog.000018", 40)}
    assert orphan_refs == {("binlog.000018", 500)}


# ── Evidence integrity ───────────────────────────────────────────────────────


def test_duplicate_event_positions_are_reported_and_deduplicated() -> None:
    """Two events cannot share a position in one log."""
    events = [ev("UPDATE", 100), ev("UPDATE", 100)]
    markers = [marker("committed", 90, 110, event_positions=(100,), gtid_sequence=1)]
    result = group(events, markers)

    assert "R-GRP-013" in rule_ids(result)
    assert len(result.transactions[0].events) == 1


def test_missing_provenance_is_reported_once_per_file_not_per_event() -> None:
    events = [ev("UPDATE", p, with_provenance=False) for p in (100, 110, 120)]
    markers = [marker("committed", 90, 130, event_positions=(100, 110, 120), gtid_sequence=1)]
    result = group(events, markers)

    prov_findings = [f for f in result.findings if f.rule_id == "R-PROV-001"]
    assert len(prov_findings) == 1


def test_every_finding_cites_a_rule_and_a_subject() -> None:
    events = [ev("UPDATE", 40), ev("UPDATE", 100)]
    markers = [marker("incomplete", 90, 110, event_positions=(100,), gtid_sequence=1)]
    result = group(events, markers, inv=None)

    assert result.findings
    for finding in result.findings:
        assert finding.rule_id
        assert finding.subject.id
