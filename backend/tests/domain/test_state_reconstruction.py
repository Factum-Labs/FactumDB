"""StateReconstructionService: ds12, plus durability assertions on ds03 and ds04.

ds12 is the partial-row-image case. The rest of this file is mostly about what
the service refuses to do: extrapolate backwards, fill in a column the evidence
never showed, or apply an event whose transaction was never observed to commit.

The durability tests are the ones that matter most. A rolled-back update that
leaks into the reconstructed state would make the engine assert a database value
that never existed.
"""

from __future__ import annotations

from decimal import Decimal

from core.domain.models.history import StepKind
from core.domain.models.values import UNOBSERVED, Presence, UndecodableValue
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.state_reconstruction import StateReconstructionService
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.builders import accounts_schema, ev, inventory, marker, phys
from tests.fixtures.inmemory import (
    InMemoryEventSource,
    InMemoryEvidenceContext,
    InMemoryPhysicalRecordSource,
    InMemorySchemaCatalog,
)

SINGLE_LOG = inventory("binlog.000018")
_DEFAULT = object()


def reconstruct(events, markers, *, records=(), schemas=None, inv=_DEFAULT):  # type: ignore[no-untyped-def]
    schemas = schemas or (accounts_schema(),)
    catalogue = InMemorySchemaCatalog(*schemas)
    evidence = InMemoryEvidenceContext(
        inventory=SINGLE_LOG if inv is _DEFAULT else inv,
        physical_tables=frozenset((s.database, s.table) for s in schemas),
    )
    source = InMemoryPhysicalRecordSource(*records)
    grouping = TransactionGroupingService(evidence).group(InMemoryEventSource(events, markers))
    correlation = RecordCorrelationService(catalogue, source, evidence).correlate(grouping)
    return StateReconstructionService(catalogue, source, evidence).reconstruct(
        grouping, correlation
    )


def committed(*positions: int, seq: int = 1):  # type: ignore[no-untyped-def]
    return marker("committed", 90, 9999, event_positions=positions, gtid_sequence=seq)


def rule_ids(result) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.rule_id for f in result.findings}


# ── Basic replay ─────────────────────────────────────────────────────────────


def test_insert_update_delete_replays_to_absent() -> None:
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "owner": "A", "balance": 5000,
                                     "status": "active"}),
            ev("UPDATE", 200, before={"account_id": 101, "balance": 5000},
               after={"account_id": 101, "owner": "A", "balance": 4000, "status": "active"}),
            ev("DELETE", 300, before={"account_id": 101, "balance": 4000}),
        ],
        [committed(100, 200, 300)],
        records=[phys("accounts", {"account_id": 101, "owner": "A", "balance": 4000,
                                   "status": "active"}, deleted=True)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.presence is Presence.ABSENT
    # Earliest observed state is absence, because the first event is an insert.
    assert history.earliest_state.presence is Presence.ABSENT
    assert [s.kind for s in history.steps][:2] == [StepKind.EARLIEST_OBSERVED, StepKind.EVENT]


def test_events_replay_in_log_order_not_timestamp_order() -> None:
    """Binlog timestamps have one-second resolution; positions are the real order."""
    result = reconstruct(
        [
            ev("UPDATE", 200, before={"account_id": 101}, after={"account_id": 101,
                                                                 "balance": 200}, seconds=0),
            ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 101,
                                                                 "balance": 100}, seconds=0),
        ],
        [committed(100, 200)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.value("balance") == 200
    assert [s.ref[1] for s in history.steps if s.ref and s.kind is StepKind.EVENT] == [100, 200]


def test_earliest_state_is_never_extrapolated_backwards() -> None:
    """An update's before-image is the earliest thing we know. Nothing before it."""
    result = reconstruct(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
            after={"account_id": 101, "balance": 4000})],
        [committed(100)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.earliest_state.value("balance") == 5000
    # Columns the before-image did not carry stay unobserved, not defaulted.
    assert history.earliest_state.value("owner") is UNOBSERVED
    assert "R-HIST-002" in rule_ids(result)


# ── ds03: rolled back is recorded but never applied ──────────────────────────


def test_ds03_rolled_back_update_is_excluded_from_the_durable_state() -> None:
    """The headline case. A rolled-back value must never be asserted as the state."""
    result = reconstruct(
        [
            ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
               after={"account_id": 101, "balance": 4000}),
            ev("UPDATE", 200, before={"account_id": 101, "balance": 4000},
               after={"account_id": 101, "balance": 3500}),
        ],
        [
            committed(100, seq=1),
            marker("rolled_back", 190, 210, event_positions=(200,), gtid_sequence=2),
        ],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.value("balance") == 4000
    # But the rolled-back value is still reachable, as an observation.
    assert history.speculative_state.value("balance") == 3500
    assert 3500 in history.produced("balance")
    assert StepKind.ROLLED_BACK_EVENT in {s.kind for s in history.steps}
    assert "R-HIST-005" in rule_ids(result)


def test_ds03_a_rolled_back_step_is_marked_not_durable() -> None:
    result = reconstruct(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
            after={"account_id": 101, "balance": 3500})],
        [marker("rolled_back", 90, 110, event_positions=(100,), gtid_sequence=1)],
    )
    history = result.history("accounts:101")
    assert history is not None
    event_steps = [s for s in history.steps if s.ref is not None and s.index > 0]
    assert all(not s.durable for s in event_steps)


# ── ds04: uncommitted is recorded but never applied ──────────────────────────


def test_ds04_incomplete_transaction_events_are_not_applied() -> None:
    """"We did not observe a commit" is not "it committed"."""
    result = reconstruct(
        [ev("UPDATE", 100, before={"account_id": 310, "balance": 900},
            after={"account_id": 310, "balance": 500})],
        [marker("incomplete", 90, 110, event_positions=(100,), gtid_sequence=1448)],
    )

    history = result.history("accounts:310")
    assert history is not None
    assert history.final_log_state.value("balance") == 900
    assert history.speculative_state.value("balance") == 500
    assert StepKind.UNCOMMITTED_EVENT in {s.kind for s in history.steps}
    assert "R-HIST-006" in rule_ids(result)


def test_ds04_ungrouped_events_are_recorded_but_not_durable() -> None:
    result = reconstruct(
        [ev("UPDATE", 500, before={"account_id": 101, "balance": 900},
            after={"account_id": 101, "balance": 500})],
        [committed(100)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.value("balance") == 900
    assert StepKind.UNCOMMITTED_EVENT in {s.kind for s in history.steps}


# ── ds12: partial row images ─────────────────────────────────────────────────


def test_ds12_columns_absent_from_the_image_are_never_defaulted() -> None:
    result = reconstruct(
        [ev("INSERT", 100, after={"account_id": 101, "balance": 5000})],
        [committed(100)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.value("balance") == 5000
    assert history.final_log_state.value("owner") is UNOBSERVED
    assert history.final_log_state.value("status") is UNOBSERVED
    assert set(history.partial_image_columns) == {"owner", "status"}
    assert "R-HIST-007" in rule_ids(result)


def test_ds12_a_column_absent_from_a_later_image_keeps_its_observed_value() -> None:
    """Absence from one image is not a change to that column."""
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "owner": "A", "balance": 5000,
                                     "status": "active"}),
            ev("UPDATE", 200, before={"account_id": 101}, after={"account_id": 101,
                                                                 "balance": 4000}),
        ],
        [committed(100, 200)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.value("balance") == 4000
    assert history.final_log_state.value("owner") == "A"


def test_ds12_partial_columns_are_reported_even_when_later_filled() -> None:
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "balance": 5000}),
            ev("UPDATE", 200, before={"account_id": 101},
               after={"account_id": 101, "owner": "A", "balance": 4000, "status": "x"}),
        ],
        [committed(100, 200)],
    )
    history = result.history("accounts:101")
    assert history is not None
    assert "owner" in history.partial_image_columns


# ── Undecodable values ───────────────────────────────────────────────────────


def test_undecodable_value_propagates_instead_of_keeping_the_previous_one() -> None:
    """Reporting a stale value as current would be a false statement."""
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "owner": "A", "balance": 5000,
                                     "status": "x"}),
            ev("UPDATE", 200, before={"account_id": 101},
               after={"account_id": 101, "owner": UndecodableValue("BLOB not supported"),
                      "balance": 4000, "status": "x"}),
        ],
        [committed(100, 200)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert isinstance(history.final_log_state.value("owner"), UndecodableValue)
    assert "R-HIST-010" in rule_ids(result)


# ── Before-image consistency ─────────────────────────────────────────────────


def test_before_image_disagreement_is_positive_evidence_of_an_unseen_change() -> None:
    """The only gap detectable without the index saying so."""
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "owner": "A", "balance": 5000,
                                     "status": "x"}),
            ev("UPDATE", 200, before={"account_id": 101, "balance": 9999},
               after={"account_id": 101, "owner": "A", "balance": 4000, "status": "x"}),
        ],
        [committed(100, 200)],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.before_image_mismatch
    assert history.gap_touched
    assert "R-HIST-008" in rule_ids(result)


def test_a_consistent_before_image_raises_no_mismatch() -> None:
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "owner": "A", "balance": 5000,
                                     "status": "x"}),
            ev("UPDATE", 200, before={"account_id": 101, "balance": 5000},
               after={"account_id": 101, "owner": "A", "balance": 4000, "status": "x"}),
        ],
        [committed(100, 200)],
    )
    history = result.history("accounts:101")
    assert history is not None
    assert not history.before_image_mismatch


def test_an_unobserved_column_cannot_contradict_a_before_image() -> None:
    """Absence of an observation is not a disagreement."""
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "balance": 5000}),
            ev("UPDATE", 200, before={"account_id": 101, "owner": "whatever"},
               after={"account_id": 101, "balance": 4000}),
        ],
        [committed(100, 200)],
    )
    history = result.history("accounts:101")
    assert history is not None
    assert not history.before_image_mismatch


def test_decimal_formatting_differences_are_not_a_mismatch() -> None:
    result = reconstruct(
        [
            ev("INSERT", 100, after={"account_id": 101, "balance": Decimal("4000.00")}),
            ev("UPDATE", 200, before={"account_id": 101, "balance": "4000.0"},
               after={"account_id": 101, "balance": Decimal("3000")}),
        ],
        [committed(100, 200)],
    )
    history = result.history("accounts:101")
    assert history is not None
    assert not history.before_image_mismatch


# ── Coverage gaps ────────────────────────────────────────────────────────────


def test_a_coverage_gap_marks_the_history_without_discarding_observations() -> None:
    """The gap limits what can be attributed; it does not erase real evidence."""
    result = reconstruct(
        [ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
            after={"account_id": 101, "balance": 4500})],
        [committed(100)],
        inv=inventory("binlog.000018", "binlog.000019", missing=("binlog.000019",)),
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.gap_touched
    assert history.coverage_gaps_touching
    # The observed value survives the gap.
    assert history.final_log_state.value("balance") == 4500
    assert StepKind.COVERAGE_GAP in {s.kind for s in history.steps}
    assert "R-HIST-009" in rule_ids(result)


def test_complete_coverage_leaves_the_history_untouched() -> None:
    result = reconstruct(
        [ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 101,
                                                              "balance": 4000})],
        [committed(100)],
    )
    history = result.history("accounts:101")
    assert history is not None
    assert not history.gap_touched


# ── Physical state ───────────────────────────────────────────────────────────


def test_physical_state_is_appended_as_an_observation() -> None:
    result = reconstruct(
        [ev("UPDATE", 100, before={"account_id": 101}, after={"account_id": 101,
                                                              "balance": 4000})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101, "balance": 3500})],
    )

    history = result.history("accounts:101")
    assert history is not None
    last = history.steps[-1]
    assert last.kind is StepKind.PHYSICAL_STATE
    # Not durable: it is a reading of the tablespace, not a replayed change.
    assert not last.durable
    assert last.presence_after is Presence.PRESENT
    assert "R-HIST-012" in rule_ids(result)


def test_a_deleted_physical_row_appends_an_absent_presence() -> None:
    result = reconstruct(
        [ev("DELETE", 100, before={"account_id": 102, "balance": 7500})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 102, "balance": 7500}, deleted=True)],
    )
    history = result.history("accounts:102")
    assert history is not None
    assert history.steps[-1].presence_after is Presence.ABSENT


def test_speculative_state_exposes_a_rolled_back_value_for_later_comparison() -> None:
    """What lets reconciliation say "the tablespace holds a rolled-back value"."""
    result = reconstruct(
        [
            ev("UPDATE", 100, before={"account_id": 101, "balance": 5000},
               after={"account_id": 101, "balance": 4000}),
            ev("UPDATE", 200, before={"account_id": 101, "balance": 4000},
               after={"account_id": 101, "balance": 3500}),
        ],
        [
            committed(100, seq=1),
            marker("rolled_back", 190, 210, event_positions=(200,), gtid_sequence=2),
        ],
        records=[phys("accounts", {"account_id": 101, "balance": 3500})],
    )

    history = result.history("accounts:101")
    assert history is not None
    assert history.final_log_state.value("balance") == 4000
    assert history.speculative_state.value("balance") == 3500
    assert 3500 in history.produced("balance")


# ── Cross-cutting ────────────────────────────────────────────────────────────


def test_a_physical_only_record_still_gets_a_history() -> None:
    result = reconstruct(
        [ev("UPDATE", 100, after={"account_id": 101})],
        [committed(100)],
        records=[phys("accounts", {"account_id": 101}),
                 phys("accounts", {"account_id": 310, "balance": 900})],
    )

    history = result.history("accounts:310")
    assert history is not None
    assert history.steps[-1].kind is StepKind.PHYSICAL_STATE
    assert history.final_log_state.presence is Presence.UNKNOWN


def test_reconstruction_is_repeatable_under_input_reordering() -> None:
    events = [
        ev("UPDATE", 200, before={"account_id": 101}, after={"account_id": 101,
                                                             "balance": 200}),
        ev("INSERT", 100, after={"account_id": 101, "balance": 100}),
    ]
    markers = [committed(100, 200)]

    first = reconstruct(events, markers)
    second = reconstruct(list(reversed(events)), markers)
    assert [h.record.id for h in first.histories] == [h.record.id for h in second.histories]
    assert first.histories[0].final_log_state.values == second.histories[0].final_log_state.values


def test_every_finding_cites_a_rule_and_a_record() -> None:
    result = reconstruct(
        [ev("INSERT", 100, after={"account_id": 101, "balance": 5000})],
        [committed(100)],
    )
    assert result.findings
    for finding in result.findings:
        assert finding.rule_id.startswith("R-")
        assert finding.subject.id
