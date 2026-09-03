"""The classification ladder is total, exclusive, and has no fall-through.

R-RECON-000 claims every field receives exactly one classification and nothing
falls through. That claim is only worth making if it is checked exhaustively, so
this walks the full product of the conditions the ladder branches on:

    value pairing  x  coverage  x  tablespace integrity  x  correlation ambiguity

and asserts every cell returns a real classification with a real rule id. It
calls `_classify` directly rather than driving the whole pipeline, because the
point is to reach cells the pipeline makes awkward to construct - and a ladder
with an unreachable branch is exactly the defect worth catching.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.models.canonical import Column
from core.domain.models.classification import ReconResult
from core.domain.models.correlation import MatchMethod, PhysicalRecordRef, RecordCorrelation
from core.domain.models.findings import SubjectKind, SubjectRef
from core.domain.models.history import ReconstructedState, RecordHistory
from core.domain.models.identity import RecordKey, RecordRef
from core.domain.models.values import UNOBSERVED, Presence, UndecodableValue, Value
from core.domain.ports import DEFAULT_SUPPORTED_TYPES
from core.domain.rules import RULES
from core.domain.services.record_reconciliation import ReconciliationService
from tests.fixtures.inmemory import (
    InMemoryEvidenceContext,
    InMemoryPhysicalRecordSource,
    InMemorySchemaCatalog,
)

RECORD = RecordRef.from_key(
    RecordKey(database="finance", table="accounts", columns=("account_id",), values=("101",))
)

BALANCE = Column(
    name="balance", position=3, data_type="decimal", is_nullable=True, is_primary_key=False
)
UNVALIDATED = Column(
    name="shape", position=9, data_type="POINT", is_nullable=True, is_primary_key=False
)

#: Every distinguishable pairing of the two sides, labelled by what it means.
VALUE_PAIRS: dict[str, tuple[Value, Value]] = {
    "equal": (Decimal("4000.00"), Decimal("4000.00")),
    "equal_across_formats": (Decimal("4000.00"), "4000.0"),
    "differ": (Decimal("4000.00"), Decimal("3500.00")),
    "both_null": (None, None),
    "null_vs_value": (None, Decimal("1")),
    "log_unobserved": (UNOBSERVED, Decimal("1")),
    "phys_unobserved": (Decimal("1"), UNOBSERVED),
    "both_unobserved": (UNOBSERVED, UNOBSERVED),
    "log_undecodable": (UndecodableValue("BLOB"), Decimal("1")),
    "phys_undecodable": (Decimal("1"), UndecodableValue("BLOB")),
    "both_undecodable": (UndecodableValue("a"), UndecodableValue("b")),
    "float": (1.5, 1.5),
    "naive_datetime": (datetime(2026, 8, 15, tzinfo=UTC), datetime(2026, 8, 15)),
    "cross_type": ("active", Decimal("1")),
}


def service() -> ReconciliationService:
    return ReconciliationService(
        InMemorySchemaCatalog(),
        InMemoryPhysicalRecordSource(),
        InMemoryEvidenceContext(),
    )


def history(*, gap: bool, partial: bool = False) -> RecordHistory:
    empty = ReconstructedState(values={}, presence=Presence.UNKNOWN)
    return RecordHistory(
        record=RECORD,
        method=MatchMethod.PK_EXACT,
        steps=(),
        earliest_state=empty,
        final_log_state=empty,
        speculative_state=empty,
        partial_image_columns=("balance",) if partial else (),
        before_image_mismatch=gap,
    )


def correlation(*, ambiguous: bool) -> RecordCorrelation:
    return RecordCorrelation(
        record=RECORD,
        method=MatchMethod.AMBIGUOUS if ambiguous else MatchMethod.PK_EXACT,
        physical=None
        if ambiguous
        else PhysicalRecordRef(database="finance", table="accounts", is_deleted=False),
    )


def classify(pairing: str, *, gap: bool, damaged: bool, ambiguous: bool, column: Column = BALANCE):  # type: ignore[no-untyped-def]
    log_value, phys_value = VALUE_PAIRS[pairing]
    return service()._classify(
        history(gap=gap),
        correlation(ambiguous=ambiguous),
        column,
        log_value,
        phys_value,
        damaged,
        "damaged" if damaged else "valid",
        DEFAULT_SUPPORTED_TYPES,
        {},
        SubjectRef(SubjectKind.FIELD, "accounts:101.balance"),
    )


CELLS = list(itertools.product(VALUE_PAIRS, (False, True), (False, True), (False, True)))


# ── Totality ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pairing,gap,damaged,ambiguous", CELLS)
def test_every_cell_yields_exactly_one_real_classification(
    pairing: str, gap: bool, damaged: bool, ambiguous: bool
) -> None:
    result, rule_id, _ = classify(pairing, gap=gap, damaged=damaged, ambiguous=ambiguous)
    assert isinstance(result, ReconResult)
    assert rule_id in RULES, f"{pairing} produced unknown rule {rule_id}"
    assert RULES[rule_id].service == "reconciliation"


@pytest.mark.parametrize("pairing,gap,damaged,ambiguous", CELLS)
def test_the_rule_that_fires_declares_the_result_it_produced(
    pairing: str, gap: bool, damaged: bool, ambiguous: bool
) -> None:
    """The catalogue and the code must agree cell by cell, not just in aggregate."""
    result, rule_id, _ = classify(pairing, gap=gap, damaged=damaged, ambiguous=ambiguous)
    declared = RULES[rule_id].result
    assert declared is not None, f"{rule_id} fired as a classification but declares no result"
    assert declared is result, f"{rule_id} declares {declared} but produced {result}"


def test_the_matrix_is_large_enough_to_be_meaningful() -> None:
    """Guard the guard: a shrunken product would make every test above vacuous."""
    assert len(CELLS) == len(VALUE_PAIRS) * 8


# ── Determinism ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pairing,gap,damaged,ambiguous", CELLS)
def test_classification_is_deterministic(
    pairing: str, gap: bool, damaged: bool, ambiguous: bool
) -> None:
    first = classify(pairing, gap=gap, damaged=damaged, ambiguous=ambiguous)[:2]
    second = classify(pairing, gap=gap, damaged=damaged, ambiguous=ambiguous)[:2]
    assert first == second


# ── Precedence, asserted where it actually matters ───────────────────────────


def test_unsupported_type_outranks_everything() -> None:
    """Checked first: comparing it would rest on decoding we never validated."""
    for gap, damaged, ambiguous in itertools.product((False, True), repeat=3):
        result, rule_id, _ = classify(
            "equal", gap=gap, damaged=damaged, ambiguous=ambiguous, column=UNVALIDATED
        )
        assert (result, rule_id) == (ReconResult.UNSUPPORTED, "R-RECON-008")


def test_undecodable_outranks_ambiguity_and_damage() -> None:
    for pairing in ("log_undecodable", "phys_undecodable", "both_undecodable"):
        result, rule_id, _ = classify(pairing, gap=False, damaged=True, ambiguous=True)
        assert (result, rule_id) == (ReconResult.UNSUPPORTED, "R-RECON-007")


def test_ambiguity_outranks_a_missing_physical_value() -> None:
    """Ambiguity is *why* the physical side is missing, so it is the better reason."""
    result, rule_id, _ = classify("phys_unobserved", gap=False, damaged=False, ambiguous=True)
    assert (result, rule_id) == (ReconResult.UNRESOLVED, "R-RECON-012")

    result, rule_id, _ = classify("phys_unobserved", gap=False, damaged=False, ambiguous=False)
    assert (result, rule_id) == (ReconResult.UNRESOLVED, "R-RECON-006")


def test_damage_outranks_an_apparent_agreement() -> None:
    """A value from a damaged page must not be allowed to confirm anything."""
    result, rule_id, _ = classify("equal", gap=False, damaged=True, ambiguous=False)
    assert (result, rule_id) == (ReconResult.UNRESOLVED, "R-RECON-009")


def test_a_missing_log_side_is_distinguished_from_a_missing_physical_side() -> None:
    assert classify("log_unobserved", gap=False, damaged=False, ambiguous=False)[1] == (
        "R-RECON-005"
    )
    assert classify("phys_unobserved", gap=False, damaged=False, ambiguous=False)[1] == (
        "R-RECON-006"
    )


# ── The conflict / unresolved boundary ───────────────────────────────────────


def test_a_difference_conflicts_only_when_coverage_is_complete() -> None:
    """The single most consequential branch in the engine."""
    clean = classify("differ", gap=False, damaged=False, ambiguous=False)
    assert (clean[0], clean[1]) == (ReconResult.CONFLICTING, "R-RECON-003")

    gapped = classify("differ", gap=True, damaged=False, ambiguous=False)
    assert (gapped[0], gapped[1]) == (ReconResult.UNRESOLVED, "R-RECON-004")


def test_no_cell_conflicts_while_coverage_is_incomplete() -> None:
    """Swept across the whole matrix, not just the case under test.

    A conflict asserts the evidence disagrees. Under a gap that assertion is
    unsupportable, and making it would present an evidence gap as tampering.
    """
    for pairing, damaged, ambiguous in itertools.product(VALUE_PAIRS, (False, True), (False, True)):
        result, rule_id, _ = classify(pairing, gap=True, damaged=damaged, ambiguous=ambiguous)
        assert result is not ReconResult.CONFLICTING, (
            f"{pairing} conflicted under a coverage gap via {rule_id}"
        )


def test_agreement_under_a_gap_is_strong_and_never_exact() -> None:
    for pairing in ("equal", "equal_across_formats"):
        result, rule_id, _ = classify(pairing, gap=True, damaged=False, ambiguous=False)
        assert (result, rule_id) == (ReconResult.STRONG, "R-RECON-002")


def test_null_matches_null_only_when_coverage_is_clean() -> None:
    assert classify("both_null", gap=False, damaged=False, ambiguous=False)[1] == "R-RECON-011"
    assert classify("both_null", gap=True, damaged=False, ambiguous=False)[0] is (
        ReconResult.STRONG
    )


def test_null_against_a_value_is_a_real_difference() -> None:
    result, rule_id, _ = classify("null_vs_value", gap=False, damaged=False, ambiguous=False)
    assert (result, rule_id) == (ReconResult.CONFLICTING, "R-RECON-003")


# ── Refusals ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pairing", ["float", "naive_datetime", "cross_type"])
def test_incomparable_observed_values_are_unsupported_not_conflicting(pairing: str) -> None:
    """Refusing to compare is not the same as finding a difference."""
    result, rule_id, _ = classify(pairing, gap=False, damaged=False, ambiguous=False)
    assert (result, rule_id) == (ReconResult.UNSUPPORTED, "R-RECON-010")


def test_two_unobserved_sides_report_the_log_side_first() -> None:
    """Arbitrary but fixed, so the output stays stable."""
    result, rule_id, _ = classify("both_unobserved", gap=False, damaged=False, ambiguous=False)
    assert (result, rule_id) == (ReconResult.UNRESOLVED, "R-RECON-005")


# ── Reachability ─────────────────────────────────────────────────────────────


def test_every_field_level_rule_in_the_catalogue_is_reachable() -> None:
    """A branch no input can reach is dead reasoning in a forensic tool."""
    reached = {
        classify(pairing, gap=gap, damaged=damaged, ambiguous=ambiguous)[1]
        for pairing, gap, damaged, ambiguous in CELLS
    }
    reached.add(
        classify("equal", gap=False, damaged=False, ambiguous=False, column=UNVALIDATED)[1]
    )

    field_rules = {
        rule_id
        for rule_id, definition in RULES.items()
        if rule_id.startswith("R-RECON-0")
        and definition.result is not None
        and not rule_id.startswith("R-RECON-02")  # presence rules, covered elsewhere
    }
    assert field_rules <= reached, f"unreachable: {sorted(field_rules - reached)}"


def test_all_six_classifications_appear_somewhere_in_the_matrix() -> None:
    produced = {
        classify(pairing, gap=gap, damaged=damaged, ambiguous=ambiguous)[0]
        for pairing, gap, damaged, ambiguous in CELLS
    }
    produced.add(
        classify("equal", gap=False, damaged=False, ambiguous=False, column=UNVALIDATED)[0]
    )
    # Partial is a record-level roll-up only; no single field ever yields it.
    assert produced == set(ReconResult) - {ReconResult.PARTIAL}
