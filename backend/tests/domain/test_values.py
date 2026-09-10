"""The value taxonomy: the distinctions that must never collapse."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.models.canonical import Column
from core.domain.models.values import (
    UNOBSERVED,
    Presence,
    UndecodableValue,
    compare,
    is_missing,
    render,
)

SUPPORTED = frozenset({"int", "decimal", "varchar", "datetime"})


def col(name: str = "balance", data_type: str = "decimal") -> Column:
    return Column(
        name=name, position=1, data_type=data_type, is_nullable=True, is_primary_key=False
    )


# ── The five kinds stay distinct ─────────────────────────────────────────────


def test_null_is_not_undecodable() -> None:
    """The canonical model's decision 6, asserted directly."""
    assert compare(None, UndecodableValue("BLOB")).comparable is False
    assert render(None) == "NULL"
    assert render(UndecodableValue("BLOB")) == "undecodable (BLOB)"


def test_undecodable_is_not_unobserved() -> None:
    """Both are non-comparable, but for different reasons and different results."""
    assert compare(1, UndecodableValue("BLOB")).rule_id == "R-VAL-005"
    assert compare(1, UNOBSERVED).rule_id == "R-VAL-006"


def test_is_missing_covers_exactly_the_two_markers() -> None:
    assert is_missing(UNOBSERVED)
    assert is_missing(UndecodableValue("x"))
    assert not is_missing(None)
    assert not is_missing(0)
    assert not is_missing("")


# ── Equality ─────────────────────────────────────────────────────────────────


def test_null_equals_null_is_a_real_match() -> None:
    result = compare(None, None)
    assert result.comparable and result.equal


def test_null_versus_value_is_a_real_difference() -> None:
    result = compare(None, 5)
    assert result.comparable and result.equal is False


def test_decimal_compares_by_value_across_representations() -> None:
    """The two sides come from different tools, which disagree on formatting."""
    assert compare(Decimal("4000.00"), "4000.0").equal is True
    assert compare(4000, Decimal("4000.000")).equal is True
    assert compare(Decimal("4000.00"), Decimal("4000.01")).equal is False


def test_bigint_beyond_float_precision_stays_exact() -> None:
    """9007199254740993 and ...992 are indistinguishable as JS numbers."""
    assert compare(9007199254740993, 9007199254740992).equal is False


def test_strings_are_byte_exact() -> None:
    """We do not emulate a collation we cannot observe in the evidence."""
    result = compare("Active", "active")
    assert result.comparable and result.equal is False
    assert result.rule_id == "R-VAL-003"
    assert compare("x ", "x").equal is False


def test_bool_is_not_an_int() -> None:
    """TINYINT(1) holding 1 and a boolean True are not the same observation."""
    assert compare(True, 1).comparable is False
    assert compare(True, True).equal is True


# ── Refusals ─────────────────────────────────────────────────────────────────


def test_floats_are_never_compared() -> None:
    assert compare(1.5, 1.5) == compare(1.5, 2.5)
    assert compare(1.5, 1.5).rule_id == "R-VAL-002"


def test_naive_datetime_is_not_comparable() -> None:
    aware = datetime(2026, 8, 15, 19, 6, 25, tzinfo=UTC)
    naive = datetime(2026, 8, 15, 19, 6, 25)
    assert compare(aware, naive).rule_id == "R-VAL-004"
    assert compare(aware, aware).equal is True


def test_unvalidated_column_type_taints_both_sides() -> None:
    """Checked before the values, so the report names the better reason."""
    result = compare(1, 1, col(data_type="POINT"), SUPPORTED)
    assert result.comparable is False
    assert result.rule_id == "R-VAL-007"


def test_cross_type_is_refused_not_coerced() -> None:
    assert compare("active", 1, col(data_type="varchar"), SUPPORTED).rule_id == "R-VAL-008"


@pytest.mark.parametrize(
    "left,right",
    [(UNOBSERVED, UNOBSERVED), (UndecodableValue("a"), UndecodableValue("a"))],
)
def test_markers_never_equal_even_themselves(left: object, right: object) -> None:
    """Two unreadable columns are not evidence of agreement."""
    assert compare(left, right).equal is None  # type: ignore[arg-type]


def test_incomparable_never_reports_equality() -> None:
    """`equal` is None exactly when `comparable` is False - no third state."""
    for result in (
        compare(1.0, 1.0),
        compare(UNOBSERVED, 1),
        compare(UndecodableValue("x"), 1),
        compare("a", 1),
    ):
        assert result.comparable is False and result.equal is None


# ── Rendering ────────────────────────────────────────────────────────────────


def test_non_values_render_as_prose() -> None:
    """A reader must never wonder whether "NULL" was a value or a note."""
    assert render(UNOBSERVED) == "not observed"
    assert render(datetime(2026, 8, 15, 19, 6, 25, tzinfo=UTC)) == "2026-08-15T19:06:25Z"
    assert render(Decimal("4000.00")) == "4000.00"


def test_presence_is_a_separate_question() -> None:
    assert {p.value for p in Presence} == {"present", "absent", "unknown"}
