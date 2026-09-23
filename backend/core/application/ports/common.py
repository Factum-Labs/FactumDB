"""Application common contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
