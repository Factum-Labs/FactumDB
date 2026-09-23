"""Small standard-library implementations safe for the application core."""

from datetime import datetime, timezone
from uuid import uuid4


class UuidGenerator:
    def new_id(self) -> str:
        return str(uuid4())


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
