"""The twelve evaluation datasets, with what each is expected to conclude.

These are the scenarios the week 7 evaluation plan lists, turned into evidence
the engine can actually be run against. Each carries an `Expected` block, so the
same fixtures serve three purposes: behaviour tests, golden snapshots, and the
accuracy metrics the project has to report.

Kept in one module rather than twelve files because they share a vocabulary and
are read comparatively - what makes ds08 interesting is precisely how it differs
from ds02.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from core.domain.models.canonical import (
    BinlogEvent,
    BinlogInventory,
    IntegrityResult,
    PhysicalRecord,
    Schema,
    TransactionMarker,
)
from core.domain.models.values import UndecodableValue
from tests.fixtures.builders import (
    accounts_schema,
    col,
    ev,
    integrity,
    inventory,
    marker,
    phys,
    transfers_schema,
)

ACCOUNTS = accounts_schema()
TRANSFERS = transfers_schema()

ORDER_LINES = Schema(
    database="finance",
    table="order_lines",
    columns=(
        col("order_id", 1, "int", pk=True, nullable=False),
        col("line_no", 2, "int", pk=True, nullable=False),
        col("qty", 3, "int"),
    ),
    mysql_version_id=80410,
)

AUDIT_LOG = Schema(
    database="finance",
    table="audit_log",
    columns=(col("message", 1, "varchar"), col("at", 2, "datetime")),
    mysql_version_id=80410,
)

WITH_BLOB = Schema(
    database="finance",
    table="accounts",
    columns=(*ACCOUNTS.columns, col("photo", 5, "blob"), col("location", 6, "POINT")),
    mysql_version_id=80410,
)

ONE_LOG = inventory("binlog.000018")


def row(account_id: int = 101, balance: str = "4000.00", **overrides: object) -> dict:
    base: dict = {
        "account_id": account_id,
        "owner": "Nimal",
        "balance": Decimal(balance),
        "status": "active",
    }
    base.update(overrides)
    return base


@dataclass(frozen=True, slots=True)
class Expected:
    """What a correct engine concludes about this dataset.

    Written from the evidence by hand, independently of the implementation, so
    the metrics measure the engine rather than restate it.
    """

    transactions: Mapping[str, str] = field(default_factory=dict)
    records: tuple[str, ...] = ()
    field_results: Mapping[str, str] = field(default_factory=dict)
    rules: tuple[str, ...] = ()
    #: True where the evidence cannot support a conflict anywhere in the result.
    no_conflicts: bool = False


@dataclass(frozen=True, slots=True)
class Dataset:
    id: str
    title: str
    why: str
    schemas: tuple[Schema, ...]
    events: tuple[BinlogEvent, ...] = ()
    markers: tuple[TransactionMarker, ...] = ()
    physical: tuple[PhysicalRecord, ...] = ()
    inventory: BinlogInventory | None = ONE_LOG
    integrity: Mapping[tuple[str, str], IntegrityResult] = field(default_factory=dict)
    physical_tables: frozenset[tuple[str, str]] | None = None
    expected: Expected = field(default_factory=Expected)

    @property
    def resolved_physical_tables(self) -> frozenset[tuple[str, str]]:
        """Tables an `.ibd` was registered for; defaults to every known schema."""
        if self.physical_tables is not None:
            return self.physical_tables
        return frozenset((s.database, s.table) for s in self.schemas)


def committed(*positions: int, seq: int, start: int = 90, end: int = 9999) -> TransactionMarker:
    return marker("committed", start, end, event_positions=positions, gtid_sequence=seq)


# ── ds01: single-row insert, update, delete ──────────────────────────────────

DS01 = Dataset(
    id="ds01",
    title="Single-row insert, update and delete",
    why="The simplest complete life cycle. Everything else is a variation on it.",
    schemas=(ACCOUNTS,),
    events=(
        ev("INSERT", 100, after=row(balance="5000.00")),
        ev("UPDATE", 200, before=row(balance="5000.00"), after=row(balance="4000.00")),
        ev("DELETE", 300, before=row(balance="4000.00")),
    ),
    markers=(
        committed(100, seq=1, start=90, end=110),
        committed(200, seq=2, start=190, end=210),
        committed(300, seq=3, start=290, end=310),
    ),
    physical=(phys("accounts", row(balance="4000.00"), deleted=True),),
    expected=Expected(
        transactions={"TX-1": "committed", "TX-2": "committed", "TX-3": "committed"},
        records=("accounts:101",),
        field_results={"accounts:101.record presence": "Exact"},
        rules=("R-HIST-004", "R-RECON-023"),
    ),
)

# ── ds02: the finance golden case ────────────────────────────────────────────

DS02 = Dataset(
    id="ds02",
    title="Multi-table committed transaction, all values agreeing",
    why="Architecture.md section 5's worked example. The clean baseline.",
    schemas=(ACCOUNTS, TRANSFERS),
    events=(
        ev("UPDATE", 100, before=row(balance="5000.00"), after=row(balance="4000.00")),
        ev("UPDATE", 110, before=row(205, "1000.00"), after=row(205, "2000.00")),
        ev("INSERT", 120, table="transfers",
           after={"transfer_id": 9001, "amount": Decimal("1000.00"), "status": "done"}),
    ),
    markers=(committed(100, 110, 120, seq=1452),),
    physical=(
        phys("accounts", row(balance="4000.00")),
        phys("accounts", row(205, "2000.00")),
        phys("transfers", {"transfer_id": 9001, "amount": Decimal("1000.00"),
                           "status": "done"}),
    ),
    expected=Expected(
        transactions={"TX-1452": "committed"},
        records=("accounts:101", "accounts:205", "transfers:9001"),
        field_results={
            "accounts:101.balance": "Exact",
            "accounts:205.balance": "Exact",
            "transfers:9001.status": "Exact",
        },
        rules=("R-CORR-001", "R-GRP-001", "R-RECON-001"),
        no_conflicts=True,
    ),
)

# ── ds03: rolled back ────────────────────────────────────────────────────────

DS03 = Dataset(
    id="ds03",
    title="Rolled-back transaction whose value appears in the tablespace",
    why=(
        "The tablespace holds a value only a rolled-back transaction produced. The "
        "engine must report the coincidence without concluding how it got there."
    ),
    schemas=(ACCOUNTS,),
    events=(
        ev("UPDATE", 100, before=row(balance="5000.00"), after=row(balance="4000.00")),
        ev("UPDATE", 200, before=row(balance="4000.00"), after=row(balance="3500.00")),
    ),
    markers=(
        committed(100, seq=1452, start=90, end=110),
        marker("rolled_back", 190, 210, event_positions=(200,), gtid_sequence=1449),
    ),
    physical=(phys("accounts", row(balance="3500.00")),),
    expected=Expected(
        transactions={"TX-1452": "committed", "TX-1449": "rolled_back"},
        records=("accounts:101",),
        field_results={"accounts:101.balance": "Conflicting"},
        rules=("R-GRP-003", "R-HIST-005", "R-RECON-003", "R-RECON-030"),
    ),
)

# ── ds04: incomplete transaction ─────────────────────────────────────────────

DS04 = Dataset(
    id="ds04",
    title="Transaction left open where the log ends",
    why="No terminator was observed, so its events never became durable.",
    schemas=(ACCOUNTS,),
    events=(ev("UPDATE", 1180, before=row(310, "900.00"), after=row(310, "500.00")),),
    markers=(marker("incomplete", 1170, 1190, event_positions=(1180,), gtid_sequence=1448),),
    physical=(phys("accounts", row(310, "900.00")),),
    expected=Expected(
        # Strong, not Exact: the values agree, but the log ends mid-transaction,
        # so the agreement cannot be asserted as complete.
        transactions={"TX-1448": "incomplete"},
        records=("accounts:310",),
        field_results={"accounts:310.balance": "Strong"},
        rules=("R-COV-003", "R-GRP-004", "R-HIST-006", "R-RECON-002"),
        no_conflicts=True,
    ),
)

# ── ds05: interleaved concurrent sessions ────────────────────────────────────

DS05 = Dataset(
    id="ds05",
    title="Two concurrent sessions interleaved in the log",
    why=(
        "Events from two threads alternate by position. Membership must follow "
        "session identity, never adjacency."
    ),
    schemas=(ACCOUNTS,),
    events=(
        ev("UPDATE", 100, thread_id=13, before=row(balance="5000.00"),
           after=row(balance="4000.00")),
        ev("UPDATE", 110, thread_id=27, before=row(205, "1000.00"), after=row(205, "900.00")),
        ev("UPDATE", 120, thread_id=13, before=row(balance="4000.00"),
           after=row(balance="3000.00")),
        ev("UPDATE", 130, thread_id=27, before=row(205, "900.00"), after=row(205, "800.00")),
    ),
    markers=(
        marker("committed", 90, 125, event_positions=(100, 120), thread_id=13, gtid_sequence=1),
        marker("committed", 105, 135, event_positions=(110, 130), thread_id=27, gtid_sequence=2),
    ),
    physical=(
        phys("accounts", row(balance="3000.00")),
        phys("accounts", row(205, "800.00")),
    ),
    expected=Expected(
        transactions={"TX-1": "committed", "TX-2": "committed"},
        records=("accounts:101", "accounts:205"),
        field_results={"accounts:101.balance": "Exact", "accounts:205.balance": "Exact"},
        rules=("R-GRP-007",),
        no_conflicts=True,
    ),
)

# ── ds06: composite primary key ──────────────────────────────────────────────

DS06 = Dataset(
    id="ds06",
    title="Composite primary key",
    why="Identity spans two columns, and their order is what makes it stable.",
    schemas=(ORDER_LINES,),
    events=(
        ev("UPDATE", 100, table="order_lines",
           before={"order_id": 5001, "line_no": 2, "qty": 1},
           after={"order_id": 5001, "line_no": 2, "qty": 3}),
    ),
    markers=(committed(100, seq=1),),
    physical=(phys("order_lines", {"order_id": 5001, "line_no": 2, "qty": 3}),),
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("order_lines:5001|2",),
        field_results={"order_lines:5001|2.qty": "Exact"},
        rules=("R-CORR-002",),
        no_conflicts=True,
    ),
)

# ── ds07: primary key update ─────────────────────────────────────────────────

DS07 = Dataset(
    id="ds07",
    title="Primary key changed by an update",
    why="One row keeps one identity across a key change, per ADR-02.",
    schemas=(ACCOUNTS,),
    events=(
        ev("UPDATE", 100, before=row(101, "5000.00"), after=row(111, "5000.00")),
        ev("UPDATE", 110, before=row(111, "5000.00"), after=row(111, "4000.00")),
    ),
    markers=(committed(100, 110, seq=1),),
    physical=(phys("accounts", row(111, "4000.00")),),
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("accounts:111",),
        field_results={"accounts:111.balance": "Exact"},
        rules=("R-CORR-010", "R-HIST-011"),
        no_conflicts=True,
    ),
)

# ── ds08: missing binlog file ────────────────────────────────────────────────

DS08 = Dataset(
    id="ds08",
    title="Values differ across a missing binary log",
    why=(
        "Architecture.md section 5.14. The states differ, but the log we were not "
        "given could hold the change that explains it. Never a conflict."
    ),
    schemas=(ACCOUNTS,),
    events=(
        ev("UPDATE", 100, before=row(balance="5000.00"), after=row(balance="4500.00")),
    ),
    markers=(committed(100, seq=1),),
    physical=(phys("accounts", row(balance="4000.00")),),
    inventory=inventory("binlog.000018", "binlog.000019", missing=("binlog.000019",)),
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("accounts:101",),
        field_results={"accounts:101.balance": "Unresolved"},
        rules=("R-COV-002", "R-HIST-009", "R-RECON-004"),
        no_conflicts=True,
    ),
)

# ── ds09: unsupported and undecodable values ─────────────────────────────────

DS09 = Dataset(
    id="ds09",
    title="Undecodable value and an unvalidated column type",
    why=(
        "Two different reasons a comparison cannot be made, and they must not be "
        "conflated. `owner` is a supported type whose bytes could not be decoded "
        "- 'we could not read it'. `location` is a type outside the validated "
        "scope - 'we never verified how to read it'. The type check runs first, "
        "so an undecodable value in an unsupported column reports the type, which "
        "is why `owner` rather than `photo` carries the undecodable marker here."
    ),
    schemas=(WITH_BLOB,),
    events=(
        ev("INSERT", 100, after={**row(), "owner": UndecodableValue("bad charset"),
                                 "photo": "x", "location": "POINT(1 1)"}),
    ),
    markers=(committed(100, seq=1),),
    physical=(phys("accounts", {**row(), "photo": "x", "location": "POINT(1 1)"}),),
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("accounts:101",),
        field_results={
            "accounts:101.owner": "Unsupported",
            "accounts:101.photo": "Unsupported",
            "accounts:101.location": "Unsupported",
            "accounts:101.balance": "Exact",
        },
        rules=("R-HIST-010", "R-RECON-007", "R-RECON-008"),
        no_conflicts=True,
    ),
)

# ── ds10: damaged tablespace ─────────────────────────────────────────────────

DS10 = Dataset(
    id="ds10",
    title="Damaged InnoDB pages",
    why="A value read from a damaged page cannot confirm or contradict anything.",
    schemas=(ACCOUNTS,),
    events=(
        ev("UPDATE", 100, before=row(balance="5000.00"), after=row(balance="4000.00")),
    ),
    markers=(committed(100, seq=1),),
    physical=(phys("accounts", row(balance="1.00")),),
    integrity={("finance", "accounts"): integrity("damaged", damaged_pages=3)},
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("accounts:101",),
        field_results={"accounts:101.balance": "Unresolved"},
        rules=("R-RECON-009",),
        no_conflicts=True,
    ),
)

# ── ds11: table with no primary key ──────────────────────────────────────────

DS11 = Dataset(
    id="ds11",
    title="Table with no primary key",
    why=(
        "InnoDB's hidden row id is invisible to mysqlbinlog, so no identity the "
        "log and the tablespace both express exists. Nothing is correlated."
    ),
    schemas=(AUDIT_LOG,),
    events=(ev("INSERT", 100, table="audit_log", after={"message": "x"}),),
    markers=(committed(100, seq=1),),
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("audit_log:*",),
        field_results={"audit_log:*.record presence": "Unsupported"},
        rules=("R-CORR-020", "R-ROLL-006"),
        no_conflicts=True,
    ),
)

# ── ds12: partial row image ──────────────────────────────────────────────────

DS12 = Dataset(
    id="ds12",
    title="Partial row image",
    why=(
        "The image omits columns. They must stay unobserved rather than being "
        "defaulted, and an agreement under that limitation is Strong, not Exact."
    ),
    schemas=(ACCOUNTS,),
    events=(
        ev("INSERT", 100, after={"account_id": 101, "balance": Decimal("4000.00")}),
    ),
    markers=(committed(100, seq=1),),
    physical=(phys("accounts", row(balance="4000.00")),),
    expected=Expected(
        transactions={"TX-1": "committed"},
        records=("accounts:101",),
        field_results={
            # balance was carried by the image and coverage is clean, so it is
            # Exact. A partial image limits the columns it omitted, not the ones
            # it carried - the limitation is per field, not per record.
            "accounts:101.balance": "Exact",
            "accounts:101.owner": "Unresolved",
            "accounts:101.status": "Unresolved",
        },
        rules=("R-HIST-007", "R-RECON-001", "R-RECON-005"),
        no_conflicts=True,
    ),
)


DATASETS: Mapping[str, Dataset] = {
    d.id: d
    for d in (DS01, DS02, DS03, DS04, DS05, DS06, DS07, DS08, DS09, DS10, DS11, DS12)
}

ALL = tuple(DATASETS.values())
