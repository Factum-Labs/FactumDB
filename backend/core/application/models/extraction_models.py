"""Application request, response and transfer contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar
from core.domain.models.canonical import (
    AnalysisWarning, BinlogEvent, PhysicalRecord, Schema, TransactionMarker,
)


@dataclass(frozen=True, slots=True)
class DecodedBinlog:
    events: tuple[BinlogEvent, ...]
    markers: tuple[TransactionMarker, ...]
    warnings: tuple[AnalysisWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedEvidence:
    schemas: tuple[Schema, ...]
    physical_records: tuple[PhysicalRecord, ...]
    events: tuple[BinlogEvent, ...]
    markers: tuple[TransactionMarker, ...]


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProvenancedBatch(Generic[T]):
    value: T
    tool_run_id: str


@dataclass(frozen=True, slots=True)
class ProvenancedResult(Generic[T]):
    """A parsed utility result tied to every command that contributed to it."""

    value: T
    primary_tool_run_id: str
    contributing_tool_run_ids: tuple[str, ...]
    batches: tuple[ProvenancedBatch[T], ...] = ()

    def __post_init__(self) -> None:
        if not self.primary_tool_run_id:
            raise ValueError("primary_tool_run_id must not be empty")
        if self.primary_tool_run_id not in self.contributing_tool_run_ids:
            raise ValueError("primary tool run must be a contributing tool run")


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    case_id: str
    operation: str
    completed_at: datetime
    item_count: int
    tool_run_ids: tuple[str, ...] = ()
