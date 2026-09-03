"""What `RecordCorrelationService` produces: which events touched which records.

The load-bearing idea is that a record identity is only ever created from an
identity the evidence actually expresses - a primary key present in a row image
or on a page. Where that is unavailable or ambiguous, no identity is invented and
the gap is reported instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from core.domain.models.canonical import EventRef, EventType, ProvenanceReference
from core.domain.models.findings import Finding
from core.domain.models.identity import RecordRef


class MatchMethod(StrEnum):
    """How a record identity was established, or why it could not be.

    Recorded per record because a forensic report has to be able to say not just
    what matched but on what basis - "primary-key exact match (account_id)" is
    the provenance line the UI renders.
    """

    PK_EXACT = "primary_key_exact"
    COMPOSITE_PK_EXACT = "composite_primary_key_exact"
    PK_UPDATE_CONTINUITY = "primary_key_update_continuity"
    LOG_ONLY = "log_only_no_physical_counterpart"
    PHYSICAL_ONLY = "physical_only_no_log_events"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED_NO_PK = "table_has_no_primary_key"
    UNSUPPORTED_NO_SCHEMA = "schema_not_available"
    UNSUPPORTED_PARTIAL_KEY = "key_columns_not_in_row_image"

    @property
    def is_supported(self) -> bool:
        return self not in {
            MatchMethod.UNSUPPORTED_NO_PK,
            MatchMethod.UNSUPPORTED_NO_SCHEMA,
            MatchMethod.UNSUPPORTED_PARTIAL_KEY,
        }

    @property
    def is_ambiguous(self) -> bool:
        return self is MatchMethod.AMBIGUOUS


@dataclass(frozen=True, slots=True)
class PhysicalRecordRef:
    """A row on a page, located precisely enough to check against raw bytes.

    `page_no` and `page_offset` are what make a reported value verifiable in a
    hex editor, which is the reason the canonical model carries them at all.
    """

    database: str
    table: str
    is_deleted: bool
    page_no: int | None = None
    page_offset: int | None = None
    provenance: ProvenanceReference | None = None

    @property
    def location(self) -> str:
        if self.page_no is None or self.page_offset is None:
            return "location not recorded"
        return f"page {self.page_no} offset {self.page_offset}"


@dataclass(frozen=True, slots=True)
class EventCorrelation:
    """One event, and the record it was linked to - or why it was not."""

    ref: EventRef
    event_type: EventType
    method: MatchMethod
    rule_id: str
    transaction_id: str | None = None
    record_id: str | None = None
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True, slots=True)
class CorrelationEdge:
    """A transaction touched a record. Maps 1:1 onto the frontend edge.

    Deduplicated on `(tx_id, record_id, event_type)` - two updates to the same
    record in one transaction are one edge on the graph. `event_refs` keeps every
    contributing event so the edge can still be traced back to exact log
    positions, which deduplication would otherwise throw away.
    """

    tx_id: str
    record_id: str
    event_type: EventType
    event_refs: tuple[EventRef, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordCorrelation:
    """One logical record, its events, and its physical counterpart if any."""

    record: RecordRef
    method: MatchMethod
    log_event_refs: tuple[EventRef, ...] = ()
    transaction_ids: tuple[str, ...] = ()
    physical: PhysicalRecordRef | None = None
    physical_candidates: tuple[PhysicalRecordRef, ...] = ()
    identity_aliases: tuple[RecordRef, ...] = ()
    findings: tuple[Finding, ...] = ()
    provenance: tuple[ProvenanceReference, ...] = ()

    @property
    def has_log_evidence(self) -> bool:
        return bool(self.log_event_refs)

    @property
    def has_physical_evidence(self) -> bool:
        return self.physical is not None


@dataclass(frozen=True, slots=True)
class UnsupportedTable:
    """A table whose events cannot be correlated at all, and why."""

    database: str
    table: str
    rule_id: str

    @property
    def qualified_name(self) -> str:
        return f"{self.database}.{self.table}"


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    records: tuple[RecordCorrelation, ...]
    edges: tuple[CorrelationEdge, ...]
    event_correlations: tuple[EventCorrelation, ...]
    unsupported_tables: tuple[UnsupportedTable, ...] = ()
    findings: tuple[Finding, ...] = ()

    def record(self, record_id: str) -> RecordCorrelation | None:
        for correlation in self.records:
            if correlation.record.id == record_id:
                return correlation
        return None


#: Which row image carries the identity, per event type. A DELETE's identity is
#: in its before-image because it has no after-image at all, and an INSERT's is
#: in its after-image for the mirror reason.
IDENTITY_IMAGE: dict[EventType, Literal["before", "after", "both"]] = {
    "INSERT": "after",
    "UPDATE": "both",
    "DELETE": "before",
}
