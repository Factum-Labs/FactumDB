"""Terse constructors for canonical objects.

Datasets read like the evidence they describe, not like dataclass calls, so the
defaults here cover everything a scenario is not specifically about.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from core.domain.models.canonical import (
    BinlogEvent,
    BinlogInventory,
    Column,
    EventType,
    IntegrityResult,
    MarkerStatus,
    PhysicalRecord,
    ProvenanceReference,
    Schema,
    TransactionMarker,
)
from core.domain.models.values import Value

GTID_UUID = "cb4d5c8e-9325-11f1-9975-00155dc1157f"
BASE_TIME = datetime(2026, 8, 15, 19, 6, 25, tzinfo=UTC)


def col(
    name: str,
    position: int,
    data_type: str = "int",
    *,
    pk: bool = False,
    nullable: bool = True,
) -> Column:
    return Column(
        name=name,
        position=position,
        data_type=data_type,
        is_nullable=nullable,
        is_primary_key=pk,
    )


def accounts_schema(database: str = "finance") -> Schema:
    """The table from the canonical model document's own test evidence."""
    return Schema(
        database=database,
        table="accounts",
        columns=(
            col("account_id", 1, "int", pk=True, nullable=False),
            col("owner", 2, "varchar"),
            col("balance", 3, "decimal"),
            col("status", 4, "varchar"),
        ),
        mysql_version_id=80410,
    )


def transfers_schema(database: str = "finance") -> Schema:
    return Schema(
        database=database,
        table="transfers",
        columns=(
            col("transfer_id", 1, "int", pk=True, nullable=False),
            col("amount", 2, "decimal"),
            col("status", 3, "varchar"),
        ),
        mysql_version_id=80410,
    )


def provenance(
    source_file: str,
    log_position: int | None = None,
    tool_name: str = "mysqlbinlog",
) -> ProvenanceReference:
    return ProvenanceReference(
        evidence_id="ev_b7785a0c",
        tool_name=tool_name,
        tool_run_id="run_3f21c8de",
        source_file=source_file,
        log_position=log_position,
    )


def ev(
    event_type: EventType,
    log_position: int,
    *,
    source_file: str = "binlog.000018",
    table: str = "accounts",
    database: str = "finance",
    before: Mapping[str, Value] | None = None,
    after: Mapping[str, Value] | None = None,
    gtid: str | None = None,
    thread_id: int | None = 13,
    seconds: int = 0,
    with_provenance: bool = True,
) -> BinlogEvent:
    return BinlogEvent(
        event_type=event_type,
        database=database,
        table=table,
        before=before,
        after=after,
        timestamp=BASE_TIME.replace(second=BASE_TIME.second + seconds),
        raw_timestamp="260816  0:36:25",
        log_position=log_position,
        source_file=source_file,
        gtid=gtid,
        thread_id=thread_id,
        provenance=provenance(source_file, log_position) if with_provenance else None,
    )


def marker(
    status: MarkerStatus,
    start_position: int,
    end_position: int,
    *,
    source_file: str = "binlog.000018",
    event_positions: tuple[int, ...] = (),
    gtid_sequence: int | None = None,
    gtid: str | None = None,
    xid: int | None = None,
    thread_id: int | None = 13,
) -> TransactionMarker:
    resolved_gtid = gtid
    if resolved_gtid is None and gtid_sequence is not None:
        resolved_gtid = f"{GTID_UUID}:{gtid_sequence}"
    return TransactionMarker(
        status=status,
        start_position=start_position,
        end_position=end_position,
        source_file=source_file,
        event_positions=event_positions,
        gtid=resolved_gtid,
        xid=xid,
        thread_id=thread_id,
        provenance=provenance(source_file, start_position),
    )


def phys(
    table: str,
    values: Mapping[str, Value],
    *,
    database: str = "finance",
    deleted: bool = False,
    page_no: int = 4,
    page_offset: int = 170,
) -> PhysicalRecord:
    return PhysicalRecord(
        database=database,
        table=table,
        values=dict(values),
        is_deleted=deleted,
        page_no=page_no,
        page_offset=page_offset,
        provenance=provenance(f"{table}.ibd", None, tool_name="ibd2sql"),
    )


def inventory(*files: str, missing: tuple[str, ...] = ()) -> BinlogInventory:
    """Listed files as the index stores them - absolute paths.

    The absolute paths are deliberate: the index really does store them, and the
    domain has to compare on file names only. A fixture using bare names would
    never exercise that.
    """
    listed = tuple(f"/var/log/mysql/{f}" for f in files)
    return BinlogInventory(
        index_file="mysql-bin.index",
        listed_files=listed,
        present_files=tuple(f"/var/log/mysql/{f}" for f in files if f not in missing),
        missing_files=tuple(f"/var/log/mysql/{f}" for f in missing),
    )


def integrity(status: str = "valid", damaged_pages: int = 0) -> IntegrityResult:
    return IntegrityResult(
        total_pages=7,
        damaged_pages=damaged_pages,
        status=status,  # type: ignore[arg-type]
        page_counts={"Index page": 1, "SDI Index page": 1, "Undo log page": 0},
        raw_summary="",
    )
