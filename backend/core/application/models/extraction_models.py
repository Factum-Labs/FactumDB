"""Application request, response and transfer contracts."""

from dataclasses import dataclass
from datetime import datetime
from core.domain.models.canonical import BinlogEvent, PhysicalRecord, Schema, TransactionMarker


@dataclass(frozen=True, slots=True)
class DecodedBinlog:
    events: tuple[BinlogEvent, ...]
    markers: tuple[TransactionMarker, ...]


@dataclass(frozen=True, slots=True)
class NormalizedEvidence:
    schemas: tuple[Schema, ...]
    physical_records: tuple[PhysicalRecord, ...]
    events: tuple[BinlogEvent, ...]
    markers: tuple[TransactionMarker, ...]


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    case_id: str
    operation: str
    completed_at: datetime
    item_count: int
