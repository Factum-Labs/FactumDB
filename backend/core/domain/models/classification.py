"""The six reconciliation classifications and their severity ordering.

Split into its own module because both the ordering helpers and the
reconciliation service need it, and neither should have to import the other.

The definitions come from the project description section 4.10:

    Exact        reconstructed and physical values agree
    Strong       key and all available comparable fields agree, some unavailable
    Partial      only part of the record can be compared
    Conflicting  the available evidence disagrees
    Unresolved   evidence is insufficient for a reliable conclusion
    Unsupported  the input or data type is outside the validated scope
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class ReconResult(StrEnum):
    """Values match the frontend `ReconResult` strings exactly."""

    EXACT = "Exact"
    STRONG = "Strong"
    PARTIAL = "Partial"
    CONFLICTING = "Conflicting"
    UNRESOLVED = "Unresolved"
    UNSUPPORTED = "Unsupported"


#: Higher wins when rolling per-field results up to a record. A literal copy of
#: the table in `frontend/src/lib/correlation.ts`; a test asserts it stays
#: identical so the two implementations cannot drift.
#:
#: This ranks *severity*, not confidence. Unsupported sits at 0 because nothing
#: about it demands the examiner's attention, NOT because it indicates
#: agreement - a record whose every field is Unsupported was never compared at
#: all, and must never be presented as agreeing.
SEVERITY: Final[Mapping[ReconResult, int]] = MappingProxyType(
    {
        ReconResult.CONFLICTING: 5,
        ReconResult.UNRESOLVED: 4,
        ReconResult.PARTIAL: 3,
        ReconResult.STRONG: 2,
        ReconResult.EXACT: 1,
        ReconResult.UNSUPPORTED: 0,
    }
)

#: A record is "flagged" - and so gets a correlation graph - if any field landed
#: on one of these.
FLAG_RESULTS: Final[frozenset[ReconResult]] = frozenset(
    {ReconResult.CONFLICTING, ReconResult.UNRESOLVED}
)


def is_flag_result(result: ReconResult) -> bool:
    return result in FLAG_RESULTS


def most_severe(results: tuple[ReconResult, ...]) -> ReconResult | None:
    """The highest-severity result, or None when nothing was classified."""
    if not results:
        return None
    return max(results, key=lambda r: SEVERITY[r])
