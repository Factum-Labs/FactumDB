"""The value taxonomy: five facts that must never collapse into each other.

This is the most load-bearing module in the domain. Every reconciliation result
ultimately comes from `compare()` below, and every one of the distinctions here
exists because collapsing it would make the tool state something about the
evidence that is not true.

    scalar               an observed value
    None                 a real SQL NULL, observed
    UndecodableValue     the column exists, its bytes could not be read
    UNOBSERVED           there is no evidence about this column at all
    Presence             record-level existence, which is a separate question

`None` versus `UndecodableValue` is the canonical model's decision 6: reporting
"the value was NULL" when we actually mean "we could not read it" is a false
statement about the database.

`UndecodableValue` versus `UNOBSERVED` is the domain's own version of the same
distinction one level up. "We read this column and could not decode it" leads to
Unsupported; "no image in evidence ever mentioned this column" leads to
Unresolved. Both are non-comparable, but a report that confuses them misdescribes
what was actually examined.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from core.domain.models.canonical import Column


@dataclass(frozen=True, slots=True)
class UndecodableValue:
    """The adapter saw that a column exists but could not decode its bytes.

    Serialized as ``{"__undecodable__": reason}`` - MySQL column values are always
    scalars, so a dict appearing where a value belongs can only be this marker.
    """

    reason: str


@dataclass(frozen=True, slots=True)
class Unobserved:
    """No evidence in this case says anything about this column.

    Domain-only: the adapters have no reason to emit it, because an adapter can
    only report what a tool actually printed. It appears when the domain builds a
    full-width row (every schema column) out of partial row images.
    """

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNOBSERVED"


#: The single instance. Compare with `is UNOBSERVED`, never with `==`.
UNOBSERVED: Final[Unobserved] = Unobserved()


class Presence(StrEnum):
    """Whether the record itself exists, as distinct from what its columns hold."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


Value = int | str | Decimal | datetime | bool | None | UndecodableValue | Unobserved


# ── Comparison ───────────────────────────────────────────────────────────────
#
# Rule ids are duplicated as literals here rather than imported from rules.py,
# which imports nothing from this module in return. The catalogue test asserts
# every id used anywhere exists in RULES, so the two cannot drift.

R_DECIMAL_EQUALITY: Final = "R-VAL-001"
R_FLOAT_NOT_COMPARABLE: Final = "R-VAL-002"
R_STRING_BYTE_EXACT: Final = "R-VAL-003"
R_NAIVE_DATETIME: Final = "R-VAL-004"
R_UNDECODABLE: Final = "R-VAL-005"
R_UNOBSERVED: Final = "R-VAL-006"
R_UNSUPPORTED_TYPE: Final = "R-VAL-007"
R_CROSS_TYPE: Final = "R-VAL-008"


@dataclass(frozen=True, slots=True)
class Comparison:
    """The outcome of comparing two values.

    `equal` is None exactly when `comparable` is False. There is no third state
    where we compared successfully but cannot say whether the values matched.
    """

    comparable: bool
    equal: bool | None
    rule_id: str


def is_missing(value: Value) -> bool:
    """True for the two markers that are never comparable with anything."""
    return isinstance(value, (UndecodableValue, Unobserved))


def _numeric(value: Value) -> Decimal | None:
    """Coerce an observed numeric value to Decimal, or None if it is not numeric.

    `bool` is excluded deliberately: in Python it is a subclass of `int`, but a
    TINYINT(1) holding 1 and a boolean True are not the same observation, and
    silently equating them would let the tool assert a match it cannot support.

    Numeric strings are coerced because the two sides of a comparison come from
    different tools - `ibd2sql` and `mysqlbinlog` do not agree on whether a
    DECIMAL arrives as text or a number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None
    return None


def compare(
    left: Value,
    right: Value,
    column: Column | None = None,
    supported_types: frozenset[str] | None = None,
) -> Comparison:
    """Decide whether two values agree. The only place equality is decided.

    The ladder is ordered so that the reason we cannot compare is always reported
    as the most specific one available: an unsupported column type is a better
    explanation than "these are different types".
    """
    # An unvalidated column type taints both sides regardless of what they hold.
    if (
        column is not None
        and supported_types is not None
        and column.data_type.lower() not in supported_types
    ):
        return Comparison(False, None, R_UNSUPPORTED_TYPE)

    if isinstance(left, UndecodableValue) or isinstance(right, UndecodableValue):
        return Comparison(False, None, R_UNDECODABLE)

    if isinstance(left, Unobserved) or isinstance(right, Unobserved):
        return Comparison(False, None, R_UNOBSERVED)

    # Binary floating point equality is not forensically defensible: two values
    # that print identically can differ in their last bits, and two that differ
    # can compare equal after a round trip through a tool's text output.
    if isinstance(left, float) or isinstance(right, float):
        return Comparison(False, None, R_FLOAT_NOT_COMPARABLE)

    # NULL is an observation, so NULL == NULL is a real match.
    if left is None and right is None:
        return Comparison(True, True, R_DECIMAL_EQUALITY)
    if left is None or right is None:
        return Comparison(True, False, R_DECIMAL_EQUALITY)

    if isinstance(left, datetime) or isinstance(right, datetime):
        if not (isinstance(left, datetime) and isinstance(right, datetime)):
            return Comparison(False, None, R_CROSS_TYPE)
        # A naive datetime has no defined instant. Comparing one against a UTC
        # value would be comparing a wall-clock reading to a point in time.
        if left.tzinfo is None or right.tzinfo is None:
            return Comparison(False, None, R_NAIVE_DATETIME)
        return Comparison(True, left == right, R_DECIMAL_EQUALITY)

    if isinstance(left, bool) or isinstance(right, bool):
        if not (isinstance(left, bool) and isinstance(right, bool)):
            return Comparison(False, None, R_CROSS_TYPE)
        return Comparison(True, left == right, R_DECIMAL_EQUALITY)

    left_num = _numeric(left)
    right_num = _numeric(right)
    if left_num is not None and right_num is not None:
        return Comparison(True, left_num == right_num, R_DECIMAL_EQUALITY)

    if isinstance(left, str) and isinstance(right, str):
        # Byte-exact. No case folding, no trimming. MySQL's default collation is
        # case-insensitive, so 'ABC' and 'abc' will be reported as differing - we
        # do not emulate a collation we cannot observe in the evidence. Reporting
        # the difference and letting the examiner interpret it is the whole
        # "report, never guess" rule applied to strings.
        return Comparison(True, left == right, R_STRING_BYTE_EXACT)

    return Comparison(False, None, R_CROSS_TYPE)


def render(value: Value) -> str:
    """Human-readable rendering for the report and the UI.

    The three non-values render as prose so a reader is never left deciding
    whether "NULL" was a value or a note.
    """
    if isinstance(value, Unobserved):
        return "not observed"
    if isinstance(value, UndecodableValue):
        return f"undecodable ({value.reason})"
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)
