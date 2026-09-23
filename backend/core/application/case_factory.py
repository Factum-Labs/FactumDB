"""Building a new Case.

This lives in the application layer rather than on the Case model itself.
Generating an id and reading the clock are side effects, and the domain layer
is kept free of both so that replaying the same inputs always produces the
same output. The purity tests in tests/domain/test_purity.py enforce that.

Both values can be passed in explicitly, which is what a test does when it
needs a fixed case to compare against.
"""

from datetime import datetime, timezone
from uuid import uuid4

from core.domain.models.case import Case


def new_case(case_name: str, examiner: str, case_id: str = None,
             created_at: datetime = None) -> Case:
    """Create a Case, generating the id and timestamp unless they are given."""
    return Case(
        case_id=case_id if case_id is not None else str(uuid4()),
        case_name=case_name,
        examiner=examiner,
        created_at=created_at if created_at is not None
        else datetime.now(timezone.utc),
    )
