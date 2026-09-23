"""The binlog event repository.

The multi-row tests at the top are the reason this file exists in its current
shape: one statement can change several rows, all written as a single binlog
event at a single position, and the original schema lost all but one of them.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from adapters.persistence.sqlite_binlog_event_repository import SqliteBinlogEventRepository
from adapters.tools.mysqlbinlog_adapter import MysqlBinlogAdapter
from core.domain.models.canonical import BinlogEvent, Column, Schema
from tests.adapters.conftest import a_run, an_ibd

WHEN = datetime(2026, 8, 15, 19, 6, 25, tzinfo=timezone.utc)


@pytest.fixture
def binlog(connection) -> SqliteBinlogEventRepository:
    return SqliteBinlogEventRepository(connection)


@pytest.fixture
def stored(evidence, tool_runs, case_id) -> tuple:
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd"))
    return "ev-ibd", "run-1"


def an_event(account_id: int, *, event_type: str = "UPDATE",
             before: dict | None = None, after: dict | None = None,
             position: int = 1600, source_file: str = "mysql-bin.000006",
             when: datetime = WHEN, table: str = "accounts") -> BinlogEvent:
    return BinlogEvent(
        event_type=event_type,
        database="finance",
        table=table,
        before=before if before is not None else ({"account_id": account_id}
                                                  if event_type != "INSERT" else None),
        after=after if after is not None else ({"account_id": account_id}
                                               if event_type != "DELETE" else None),
        timestamp=when,
        raw_timestamp="260816  0:36:25",
        log_position=position,
        source_file=source_file,
        gtid="cb4d5c8e-9325-11f1-9975-00155dc1157f:10",
        thread_id=13,
    )


# ── One statement, several rows ──────────────────────────────────────────────


def test_every_row_of_a_multi_row_event_is_kept(binlog, stored) -> None:
    """UPDATE ... WHERE balance > 3000 matching two rows is one binlog event.

    Both row images share the event's end_log_pos. The original unique key on
    (evidence, file, position) rejected the second one - or, with INSERT OR
    REPLACE, let it silently overwrite the first.
    """
    evidence_id, run_id = stored
    binlog.save_many([an_event(101), an_event(103)], evidence_id, run_id)

    stored_rows = binlog.rows_in_event(evidence_id, ("mysql-bin.000006", 1600))

    assert [e.after["account_id"] for e in stored_rows] == [101, 103]


def test_rows_keep_the_order_they_had_in_the_event(binlog, stored) -> None:
    """The order of row images is the order MySQL applied them in."""
    evidence_id, run_id = stored
    binlog.save_many(
        [an_event(105), an_event(101), an_event(103)], evidence_id, run_id
    )

    stored_rows = binlog.rows_in_event(evidence_id, ("mysql-bin.000006", 1600))

    assert [e.after["account_id"] for e in stored_rows] == [105, 101, 103]


def test_find_by_ref_returns_the_first_row_of_a_multi_row_event(binlog, stored) -> None:
    """EventRef has no row index yet, so a lookup by ref can only name one row.

    This pins the current behaviour so it cannot change unnoticed. Once
    EventRef carries a row index this test should be replaced.
    """
    evidence_id, run_id = stored
    binlog.save_many([an_event(101), an_event(103)], evidence_id, run_id)

    found = binlog.find_by_ref(evidence_id, ("mysql-bin.000006", 1600))

    assert found.after["account_id"] == 101


def test_the_adapter_and_the_repository_agree_end_to_end(binlog, stored) -> None:
    """Real mysqlbinlog-format text for one two-row UPDATE, through both halves.

    Before the fix, the adapter emitted two events at position 1600 and the
    repository could store only one of them.
    """
    evidence_id, run_id = stored
    schema = Schema(
        database="finance",
        table="accounts",
        columns=(
            Column("account_id", 1, "int", False, True),
            Column("status", 2, "varchar(20)", True, False),
        ),
        mysql_version_id=80410,
    )
    text = """\
# original_commit_timestamp=1788532598761046 (2026-09-23 12:00:00.000000 +0530)
SET @@SESSION.GTID_NEXT= 'cb4d5c8e-9325-11f1-9975-00155dc1157f:20'/*!*/;
#260923 12:00:00 server id 1  end_log_pos 1400 CRC32 0x1 \tQuery\tthread_id=8
BEGIN
#260923 12:00:00 server id 1  end_log_pos 1450 CRC32 0x2 \tTable_map: `finance`.`accounts` mapped to number 89
#260923 12:00:00 server id 1  end_log_pos 1600 CRC32 0x3 \tUpdate_rows: table id 89 flags: STMT_END_F
### UPDATE `finance`.`accounts`
### WHERE
###   @1=101 /* INT meta=0 nullable=0 is_null=0 */
###   @2='active' /* VARSTRING(80) meta=80 nullable=1 is_null=0 */
### SET
###   @1=101 /* INT meta=0 nullable=0 is_null=0 */
###   @2='frozen' /* VARSTRING(80) meta=80 nullable=1 is_null=0 */
### UPDATE `finance`.`accounts`
### WHERE
###   @1=103 /* INT meta=0 nullable=0 is_null=0 */
###   @2='active' /* VARSTRING(80) meta=80 nullable=1 is_null=0 */
### SET
###   @1=103 /* INT meta=0 nullable=0 is_null=0 */
###   @2='frozen' /* VARSTRING(80) meta=80 nullable=1 is_null=0 */
#260923 12:00:00 server id 1  end_log_pos 1631 CRC32 0x4 \tXid = 50
COMMIT/*!*/;
"""
    events, _, _ = MysqlBinlogAdapter.parse(
        text, "mysql-bin.000024", lambda d, t: schema
    )
    binlog.save_many(events, evidence_id, run_id)

    stored_rows = binlog.rows_in_event(evidence_id, ("mysql-bin.000024", 1600))

    assert len(events) == 2
    assert [(e.before["status"], e.after["status"]) for e in stored_rows] == [
        ("active", "frozen"),
        ("active", "frozen"),
    ]
    assert {e.after["account_id"] for e in stored_rows} == {101, 103}


# ── Round-tripping ───────────────────────────────────────────────────────────


def test_an_update_round_trips(binlog, stored) -> None:
    evidence_id, run_id = stored
    event = an_event(
        101,
        before={"account_id": 101, "balance": 5000},
        after={"account_id": 101, "balance": 4000},
    )
    binlog.save_many([event], evidence_id, run_id)

    assert binlog.events() == [event]


def test_insert_has_no_before_and_delete_has_no_after(binlog, stored) -> None:
    """None means the image does not exist, which is not the same as NULL."""
    evidence_id, run_id = stored
    binlog.save_many(
        [
            an_event(102, event_type="INSERT", position=900),
            an_event(102, event_type="DELETE", position=1112),
        ],
        evidence_id, run_id,
    )

    inserted, deleted = binlog.events()

    assert inserted.before is None and inserted.after is not None
    assert deleted.after is None and deleted.before is not None


def test_a_decimal_balance_is_not_turned_into_a_float(binlog, stored) -> None:
    evidence_id, run_id = stored
    event = an_event(
        101,
        before={"balance": Decimal("5000.00")},
        after={"balance": Decimal("4000.10")},
    )
    binlog.save_many([event], evidence_id, run_id)

    loaded = binlog.events()[0]

    assert loaded.after["balance"] == Decimal("4000.10")
    assert isinstance(loaded.after["balance"], Decimal)


# ── Positions only mean something inside one file ───────────────────────────


def test_the_same_position_in_two_files_is_two_events(binlog, stored) -> None:
    """Every binlog file starts its positions again at 4."""
    evidence_id, run_id = stored
    binlog.save_many(
        [
            an_event(101, source_file="mysql-bin.000001", position=1112),
            an_event(102, source_file="mysql-bin.000006", position=1112),
        ],
        evidence_id, run_id,
    )

    assert len(binlog.events()) == 2


# ── Re-decoding ──────────────────────────────────────────────────────────────


def test_decoding_a_file_again_replaces_its_events(binlog, stored) -> None:
    evidence_id, run_id = stored
    batch = [an_event(101), an_event(103)]
    binlog.save_many(batch, evidence_id, run_id)
    binlog.save_many(batch, evidence_id, run_id)

    assert len(binlog.events()) == 2


def test_decoding_one_file_does_not_touch_another(binlog, stored) -> None:
    """Replacement is scoped to the files in the batch."""
    evidence_id, run_id = stored
    binlog.save_many([an_event(101, source_file="mysql-bin.000001")], evidence_id, run_id)
    binlog.save_many([an_event(102, source_file="mysql-bin.000006")], evidence_id, run_id)

    assert len(binlog.events()) == 2


# ── Ordering and filtering ───────────────────────────────────────────────────


def test_events_come_back_in_time_order(binlog, stored) -> None:
    evidence_id, run_id = stored
    later = an_event(103, position=2000, when=WHEN + timedelta(minutes=5))
    earlier = an_event(101, position=1000, when=WHEN)
    binlog.save_many([later, earlier], evidence_id, run_id)

    assert [e.after["account_id"] for e in binlog.events()] == [101, 103]


def test_events_in_the_same_second_have_a_stable_order(binlog, stored) -> None:
    """Header timestamps are only accurate to the second.

    All three events in the deletion scenario share 0:36:25, so the order
    has to come from file and position, or it could differ between runs.
    """
    evidence_id, run_id = stored
    binlog.save_many(
        [an_event(3, position=1112), an_event(1, position=739), an_event(2, position=985)],
        evidence_id, run_id,
    )

    assert [e.log_position for e in binlog.events()] == [739, 985, 1112]


def test_list_by_table_filters_in_sql(binlog, stored) -> None:
    evidence_id, run_id = stored
    binlog.save_many(
        [an_event(101, position=100), an_event(9001, position=200, table="transfers")],
        evidence_id, run_id,
    )

    accounts = binlog.list_by_table("finance", "accounts")

    assert [e.table for e in accounts] == ["accounts"]


def test_unknown_ref_returns_none(binlog, stored) -> None:
    evidence_id, _ = stored
    assert binlog.find_by_ref(evidence_id, ("mysql-bin.000099", 4)) is None


# ── Referential integrity ────────────────────────────────────────────────────


def test_events_need_a_real_tool_run(binlog, stored) -> None:
    evidence_id, _ = stored
    with pytest.raises(sqlite3.IntegrityError):
        binlog.save_many([an_event(101)], evidence_id, "no-such-run")
