from dataclasses import dataclass

@dataclass(frozen=True)
class CreateCaseRequest:
    """
    Represents a request to create a new case.
    """
    case_name: str
    examiner: str

@dataclass
class CreateCaseResponse:
    """
    Represents the response after creating a new case.
    """
    case_id: str
    case_name: str
    examiner: str
    created_at: str
