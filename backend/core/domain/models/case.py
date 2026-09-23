from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Case:
    """
    Represents a case in the system.

    The id and the creation time are supplied by the caller rather than
    generated here. Generating a UUID or reading the clock inside a domain
    model makes its output different on every run, which breaks repeatability
    - and being able to re-run an analysis and get the same result is a
    requirement of the whole project, not just a testing convenience.

    Use core.application.case_factory.new_case() to build one with a fresh id
    and timestamp.
    """

    case_id: str
    case_name: str
    examiner: str
    created_at: datetime
