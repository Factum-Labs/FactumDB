from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

@dataclass(frozen=True)
class Case:
    """
    Represents a case in the system.
    """
        
    case_id: str
    case_name: str
    examiner: str
    created_at: datetime

    @classmethod
    def create(cls, case_name:str, examiner:str) -> "Case":
        return cls(
            case_id=str(uuid4()),
            case_name=case_name,
            examiner=examiner,
            created_at=datetime.now(timezone.utc)
        )

