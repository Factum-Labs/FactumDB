"""The canonical model: the contract between the adapters and the domain layer.

These are the shapes defined in `docs/canonical-model.md`. Each adapter converts
one tool's output into these objects, and nothing after that point ever sees raw
command-line text. Every model here is frozen: the domain reasons about evidence,
it never edits it.

Two deviations from the document, both additive and both defaulted so existing
adapter code keeps working:

1. `provenance` on `PhysicalRecord`, `BinlogEvent` and `TransactionMarker`.
   The document keeps provenance out of the models and relies on the repositories
   storing `tool_run_id` on each row. That works for persistence but not for a
   pure domain function: a service that only sees `(source_file, log_position)`
   cannot attach a `tool_run_id` to the finding it emits, and "every finding
   carries provenance" is a hard requirement. When the field is None the services
   emit degraded provenance plus one R-PROV-001 finding, so the gap is visible
   rather than silent.

2. `Warning` is named `AnalysisWarning` here. `Warning` is a builtin exception
   class and `warnings` is a stdlib module; shadowing either inside a forensic
   codebase is a needless foot-gun.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.domain.models.values import Value

EventType = Literal["INSERT", "UPDATE", "DELETE"]
MarkerStatus = Literal["committed", "rolled_back", "incomplete"]
IntegrityStatus = Literal["valid", "damaged", "unknown"]

#: The only globally unique handle for a binlog event. `log_position` restarts
#: at 4 in every file, so it is never unique on its own.
EventRef = tuple[str, int]


@dataclass(frozen=True, slots=True)
class ProvenanceReference:
    """Where one piece of information came from.

    In forensics it is not enough to say "the balance is 4000" - every value has
    to answer "how do you know that?".
    """

    evidence_id: str
    tool_name: str
    tool_run_id: str
    source_file: str
    log_position: int | None = None


@dataclass(frozen=True, slots=True)
class Column:
    """One visible column of a table.

    `position` is the load-bearing field: `mysqlbinlog` refers to columns only by
    number (`@1`, `@2`, ...), so this is what turns those numbers into names. It
    counts only user columns - InnoDB's hidden `DB_TRX_ID`, `DB_ROLL_PTR` and
    `DB_ROW_ID` are excluded, and the adapter owns that exclusion.
    """

    name: str
    position: int
    data_type: str
    is_nullable: bool
    is_primary_key: bool


@dataclass(frozen=True, slots=True)
class Schema:
    """One table's shape, from the `ibd2sdi` adapter."""

    database: str
    table: str
    columns: tuple[Column, ...]
    mysql_version_id: int

    @property
    def qualified_name(self) -> str:
        """e.g. ``finance.accounts``."""
        return f"{self.database}.{self.table}"

    def primary_key_columns(self) -> tuple[Column, ...]:
        """PK columns in schema position order.

        Order matters: it fixes the rendering of composite keys, and a composite
        key rendered in two different orders would read as two different records.
        """
        keys = (c for c in self.columns if c.is_primary_key)
        return tuple(sorted(keys, key=lambda c: c.position))

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    def columns_in_order(self) -> tuple[Column, ...]:
        return tuple(sorted(self.columns, key=lambda c: c.position))


@dataclass(frozen=True, slots=True)
class PhysicalRecord:
    """One row as it exists in the `.ibd` file right now, from `ibd2sql`.

    `is_deleted` is a flag rather than a separate model because InnoDB itself
    represents deletion as a single header bit - the bytes stay on the page until
    purge runs. That is also why absence of deleted rows only ever supports the
    claim "no deleted records found", never "no records were deleted".

    `page_no`/`page_offset` locate the row for hex verification. `page_offset` is
    relative to the start of its page, so the absolute file position is
    ``page_no * page_size + page_offset``.
    """

    database: str
    table: str
    values: Mapping[str, Value]
    is_deleted: bool
    page_no: int | None = None
    page_offset: int | None = None
    provenance: ProvenanceReference | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.database}.{self.table}"


@dataclass(frozen=True, slots=True)
class BinlogEvent:
    """One row change decoded from a binary log, from `mysqlbinlog`.

    `before`/`after` are None when the image does not exist at all, which is a
    different fact from a column holding SQL NULL:

        INSERT  before=None      after=new row
        UPDATE  before=old row   after=new row
        DELETE  before=old row   after=None

    Both dicts use real column names; the adapter has already resolved `@N`.

    `timestamp` is UTC. `mysqlbinlog` prints server-local time with no timezone
    marker, so storing what was printed would silently corrupt event ordering the
    moment evidence arrives from another timezone. `raw_timestamp` keeps the
    tool's own text so the report can still show it verbatim.
    """

    event_type: EventType
    database: str
    table: str
    before: Mapping[str, Value] | None
    after: Mapping[str, Value] | None
    timestamp: datetime
    raw_timestamp: str
    log_position: int
    source_file: str
    gtid: str | None = None
    thread_id: int | None = None
    provenance: ProvenanceReference | None = None

    @property
    def ref(self) -> EventRef:
        return (self.source_file, self.log_position)

    @property
    def qualified_name(self) -> str:
        return f"{self.database}.{self.table}"


@dataclass(frozen=True, slots=True)
class TransactionMarker:
    """Which events were committed together, from `mysqlbinlog`.

    The adapter records only the markers it can actually see; deciding what the
    grouping *means* is the domain layer's job.

    `status` "incomplete" means the transaction started with no COMMIT or
    ROLLBACK observed - for example the binlog file we were given simply ends.
    That is evidence of a gap, so it is never discarded.

    `gtid` and `xid` are both optional because a server can run with GTID off.
    """

    status: MarkerStatus
    start_position: int
    end_position: int
    source_file: str
    event_positions: tuple[int, ...] = ()
    gtid: str | None = None
    xid: int | None = None
    thread_id: int | None = None
    provenance: ProvenanceReference | None = None


@dataclass(frozen=True, slots=True)
class IntegrityResult:
    """The physical condition of one `.ibd` file, from `innochecksum`.

    `page_counts` keeps the whole page-type breakdown including zeros. The zeros
    carry information: an `Undo log page` count of 0 is exactly why a prior value
    cannot be recovered from the tablespace at all.
    """

    total_pages: int
    damaged_pages: int
    status: IntegrityStatus
    page_counts: Mapping[str, int] = field(default_factory=dict)
    raw_summary: str = ""


@dataclass(frozen=True, slots=True)
class AnalysisWarning:
    """Something an adapter could not handle.

    A model rather than a log line because warnings have to reach the final
    report - a quietly skipped column changes how far a conclusion can be
    trusted.
    """

    code: str
    message: str
    context: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BinlogInventory:
    """The server's own list of its binary logs, built from `mysql-bin.index`.

    This is the only thing that lets us say "the server had 6 logs and we were
    given 5". Without it we have some number of files and no way to know whether
    that is all of them - which is the difference between reporting an evidence
    gap and wrongly reporting tampering.

    The index file stores absolute paths while working copies live in the case
    folder, so every comparison here is on file names only.
    """

    index_file: str
    listed_files: tuple[str, ...]
    present_files: tuple[str, ...]
    missing_files: tuple[str, ...]
