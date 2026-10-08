"""Data types: making mysqlbinlog and ibd2sql describe a value the same way.

Every row and image below is real output from scenario 4
(datasets/scenario4_types), cut down to what the parsers need. The analysis
compares the binlog side with the page side value by value, so a type the two
tools print differently shows up as a conflict that never happened - or, for
DECIMAL, used to stop the pipeline altogether.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from adapters.persistence.sqlite_binlog_event_repository import SqliteBinlogEventRepository
from adapters.persistence.sqlite_physical_record_repository import (
    SqlitePhysicalRecordRepository,
)
from adapters.tools.ibd2sql_adapter import Ibd2SqlAdapter
from adapters.tools import mysqlbinlog_adapter
from adapters.tools.mysqlbinlog_adapter import MysqlBinlogAdapter, _typed
from core.domain.models.canonical import Column, Schema
from core.domain.models.values import UndecodableValue
from tests.adapters.conftest import a_run, an_ibd

PAYMENTS = Schema("shop", "payments", (
    Column("payment_id", 1, "int", False, True),
    Column("customer", 2, "varchar(50)", False, False),
    Column("currency", 3, "char(3)", False, False),
    Column("amount", 4, "decimal(12,2)", False, False),
    Column("fee", 5, "decimal(6,3)", True, False),
    Column("status", 6, "enum('pending','paid','refunded')", False, False),
    Column("paid_on", 7, "date", True, False),
    Column("updated_at", 8, "datetime", True, False),
    Column("created_at", 9, "timestamp", True, False),
    Column("is_flagged", 10, "tinyint(1)", False, False),
    Column("note", 11, "text", True, False),
), 80411)

ATTACHMENTS = Schema("shop", "attachments", (
    Column("attachment_id", 1, "int", False, True),
    Column("content", 2, "blob", True, False),
    Column("meta", 3, "json", True, False),
), 80411)

BINLOG = """\
SET @@SESSION.GTID_NEXT= 'cb4d5c8e-9325-11f1-9975-00155dc1157f:18'/*!*/;
#261005  9:09:30 server id 1  end_log_pos 2083 CRC32 0x1fe38a5a \tQuery\tthread_id=8\texec_time=0\terror_code=0
BEGIN
#261005  9:09:30 server id 1  end_log_pos 2166 CRC32 0x903bed85 \tTable_map: `shop`.`payments` mapped to number 90
#261005  9:09:30 server id 1  end_log_pos 2338 CRC32 0x1113d498 \tWrite_rows: table id 90 flags: STMT_END_F
### INSERT INTO `shop`.`payments`
### SET
###   @1=1 /* INT meta=0 nullable=0 is_null=0 */
###   @2='Amal' /* VARSTRING(200) meta=200 nullable=0 is_null=0 */
###   @3='LKR' /* STRING(12) meta=65036 nullable=0 is_null=0 */
###   @4=5000.00 /* DECIMAL(12,2) meta=3074 nullable=0 is_null=0 */
###   @5=1.250 /* DECIMAL(6,3) meta=1539 nullable=1 is_null=0 */
###   @6=1 /* ENUM(1 byte) meta=63233 nullable=0 is_null=0 */
###   @7=NULL /* DATE meta=0 nullable=1 is_null=1 */
###   @8='2026-10-03 09:15:00' /* DATETIME(0) meta=0 nullable=1 is_null=0 */
###   @9=1790999100 /* TIMESTAMP(0) meta=0 nullable=1 is_null=0 */
###   @10=0 /* TINYINT meta=0 nullable=0 is_null=0 */
###   @11='first payment' /* BLOB/TEXT meta=2 nullable=1 is_null=0 */
### INSERT INTO `shop`.`payments`
### SET
###   @1=3 /* INT meta=0 nullable=0 is_null=0 */
###   @2='Kamal' /* VARSTRING(200) meta=200 nullable=0 is_null=0 */
###   @3='USD' /* STRING(12) meta=65036 nullable=0 is_null=0 */
###   @4=3200.75 /* DECIMAL(12,2) meta=3074 nullable=0 is_null=0 */
###   @5=0.500 /* DECIMAL(6,3) meta=1539 nullable=1 is_null=0 */
###   @6=2 /* ENUM(1 byte) meta=63233 nullable=0 is_null=0 */
###   @7='2026:10:01' /* DATE meta=0 nullable=1 is_null=0 */
###   @8='2026-10-03 09:17:00' /* DATETIME(0) meta=0 nullable=1 is_null=0 */
###   @9=1790999220 /* TIMESTAMP(0) meta=0 nullable=1 is_null=0 */
###   @10=0 /* TINYINT meta=0 nullable=0 is_null=0 */
###   @11='paid early' /* BLOB/TEXT meta=2 nullable=1 is_null=0 */
#261005  9:09:30 server id 1  end_log_pos 2369 CRC32 0x12c13d78 \tXid = 25
COMMIT/*!*/;
SET @@SESSION.GTID_NEXT= 'cb4d5c8e-9325-11f1-9975-00155dc1157f:27'/*!*/;
#261005  9:09:30 server id 1  end_log_pos 5808 CRC32 0x00000001 \tQuery\tthread_id=8\texec_time=0\terror_code=0
BEGIN
#261005  9:09:30 server id 1  end_log_pos 5891 CRC32 0xaddb980f \tTable_map: `shop`.`payments` mapped to number 90
#261005  9:09:30 server id 1  end_log_pos 5944 CRC32 0xb3a30bcb \tUpdate_rows: table id 90 flags: STMT_END_F
### UPDATE `shop`.`payments`
### WHERE
###   @1=1 /* INT meta=0 nullable=0 is_null=0 */
### SET
###   @11='checked' /* BLOB/TEXT meta=2 nullable=1 is_null=0 */
#261005  9:09:30 server id 1  end_log_pos 5975 CRC32 0xc3d7bd4f \tXid = 45
COMMIT/*!*/;
SET @@SESSION.GTID_NEXT= 'cb4d5c8e-9325-11f1-9975-00155dc1157f:28'/*!*/;
#261005  9:09:30 server id 1  end_log_pos 6100 CRC32 0x00000002 \tQuery\tthread_id=8\texec_time=0\terror_code=0
BEGIN
#261005  9:09:30 server id 1  end_log_pos 6160 CRC32 0x00000003 \tTable_map: `shop`.`attachments` mapped to number 92
#261005  9:09:30 server id 1  end_log_pos 6240 CRC32 0x00000004 \tWrite_rows: table id 92 flags: STMT_END_F
### INSERT INTO `shop`.`attachments`
### SET
###   @1=1 /* INT meta=0 nullable=0 is_null=0 */
###   @2='\\x89PNG\\r\\n\\x1a\\n' /* BLOB/TEXT meta=2 nullable=1 is_null=0 */
###   @3='{"pages": 2, "signed": true}' /* JSON meta=4 nullable=1 is_null=0 */
#261005  9:09:30 server id 1  end_log_pos 6271 CRC32 0x00000005 \tXid = 47
COMMIT/*!*/;
SET @@SESSION.GTID_NEXT= 'cb4d5c8e-9325-11f1-9975-00155dc1157f:30'/*!*/;
#261005  9:09:30 server id 1  end_log_pos 6500 CRC32 0x00000006 \tQuery\tthread_id=8\texec_time=0\terror_code=0
BEGIN
#261005  9:09:30 server id 1  end_log_pos 6583 CRC32 0x00000007 \tTable_map: `shop`.`payments` mapped to number 90
#261005  9:09:30 server id 1  end_log_pos 6700 CRC32 0x00000008 \tDelete_rows: table id 90 flags: STMT_END_F
### DELETE FROM `shop`.`payments`
### WHERE
###   @1=2 /* INT meta=0 nullable=0 is_null=0 */
###   @2='Nimal' /* VARSTRING(200) meta=200 nullable=0 is_null=0 */
###   @3='LKR' /* STRING(12) meta=65036 nullable=0 is_null=0 */
###   @4=7500.50 /* DECIMAL(12,2) meta=3074 nullable=0 is_null=0 */
###   @5=2.000 /* DECIMAL(6,3) meta=1539 nullable=1 is_null=0 */
###   @6=2 /* ENUM(1 byte) meta=63233 nullable=0 is_null=0 */
###   @7='2026:10:03' /* DATE meta=0 nullable=1 is_null=0 */
###   @8='2026-10-03 09:16:00' /* DATETIME(0) meta=0 nullable=1 is_null=0 */
###   @9=1790999160 /* TIMESTAMP(0) meta=0 nullable=1 is_null=0 */
###   @10=0 /* TINYINT meta=0 nullable=0 is_null=0 */
###   @11=NULL /* BLOB/TEXT meta=2 nullable=1 is_null=1 */
#261005  9:09:30 server id 1  end_log_pos 6731 CRC32 0x00000009 \tXid = 51
COMMIT/*!*/;
"""

COLUMNS = (
    "`payment_id`,`customer`,`currency`,`amount`,`fee`,`status`,"
    "`paid_on`,`updated_at`,`created_at`,`is_flagged`,`note`"
)
PAGE_LIVE = (
    f"INSERT INTO `shop`.`payments`({COLUMNS}) VALUES (1,'Amal','LKR',4000.10,1.250,'paid',"
    "'2026-10-03','2026-10-03 09:15:00','2026-10-03 09:15:00',1,'checked');\n"
    "INSERT INTO `shop`.`attachments`(`attachment_id`,`content`,`meta`) VALUES "
    "(1,0x89504e470d0a1a0a,'{\"pages\": 3, \"signed\": false}');\n"
)
PAGE_DELETED = (
    f"INSERT INTO `shop`.`payments`({COLUMNS}) VALUES (2,'Nimal','LKR',7500.50,2.000,'paid',"
    "'2026-10-03','2026-10-03 09:16:00','2026-10-03 09:16:00',0,null);\n"
)


@pytest.fixture
def zone(monkeypatch):
    """Supply deterministic local zones without changing the operating system.

    Windows has no time.tzset(). Patch only the adapter's datetime boundary:
    parsing and value conversion still run, and an explicit UTC conversion in
    the adapter would still fail the UTC+05:30 assertions.
    """
    local_zone = timezone.utc

    class LocalDatetime(datetime):
        @classmethod
        def fromtimestamp(cls, timestamp, tz=None):
            if tz is not None:
                return super().fromtimestamp(timestamp, tz)
            return super().fromtimestamp(timestamp, local_zone).replace(tzinfo=None)

    monkeypatch.setattr(mysqlbinlog_adapter, "datetime", LocalDatetime)

    def use(tz):
        nonlocal local_zone
        local_zone = {
            "IST-5:30": timezone(timedelta(hours=5, minutes=30)),
            "UTC0": timezone.utc,
        }[tz]

    return use


def binlog_rows():
    lookup = {"payments": PAYMENTS, "attachments": ATTACHMENTS}
    events, _, warnings = MysqlBinlogAdapter.parse(
        BINLOG, "mysql-bin.000044", lambda database, table: lookup[table]
    )
    assert warnings == []
    return events


def page_rows(text, deleted=False):
    return Ibd2SqlAdapter.parse(text, is_deleted=deleted)


# ── Each type on its own ─────────────────────────────────────────────────────


def test_decimals_keep_their_exact_value() -> None:
    """Both tools print 4000.10; a float would hold 4000.099999999999636..."""
    amal = binlog_rows()[0].after
    page = page_rows(PAGE_LIVE)[0].values

    assert (amal["amount"], amal["fee"]) == (Decimal("5000.00"), Decimal("1.250"))
    assert page["amount"] == Decimal("4000.10")
    assert type(amal["amount"]) is Decimal and type(page["amount"]) is Decimal


def test_an_enum_position_becomes_its_label() -> None:
    """mysqlbinlog prints 2 where ibd2sql prints 'paid'."""
    amal, kamal = binlog_rows()[0].after, binlog_rows()[1].after

    assert (amal["status"], kamal["status"]) == ("pending", "paid")


def test_enum_edge_cases() -> None:
    enum = "enum('it''s','x')"

    assert _typed(enum, 1) == "it's"
    assert _typed(enum, 0) == ""
    assert isinstance(_typed(enum, 9), UndecodableValue)


def test_a_colon_date_gets_dashes() -> None:
    """mysqlbinlog prints a DATE as 2026:10:01."""
    assert binlog_rows()[1].after["paid_on"] == "2026-10-01"


def test_a_timestamp_is_shown_in_the_machines_zone_like_ibd2sql(zone) -> None:
    """1790999100 is 03:45 UTC, which ibd2sql prints in the local zone."""
    zone("IST-5:30")
    assert binlog_rows()[0].after["created_at"] == "2026-10-03 09:15:00"

    zone("UTC0")
    assert binlog_rows()[0].after["created_at"] == "2026-10-03 03:45:00"


@pytest.mark.parametrize("epoch", [1790999100, Decimal("1790999100.123456")])
def test_a_timestamp_uses_the_actual_host_timezone(epoch) -> None:
    """Exercise the native local conversion on Windows as well as Unix."""
    expected = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(epoch)))
    if isinstance(epoch, Decimal):
        expected += ".123456"
    assert _typed("timestamp(6)", epoch) == expected


def test_a_datetime_is_left_alone() -> None:
    """DATETIME has no zone, and both tools print it the same way."""
    assert binlog_rows()[0].after["updated_at"] == "2026-10-03 09:15:00"


def test_binary_data_is_marked_on_both_sides_and_json_kept() -> None:
    """The tools spell the same bytes differently, and neither spelling is text."""
    log = next(e for e in binlog_rows() if e.table == "attachments").after
    page = next(r for r in page_rows(PAGE_LIVE) if r.table == "attachments").values

    assert log["content"] == page["content"] == UndecodableValue("binary data is not decoded")
    assert log["meta"] == '{"pages": 2, "signed": true}'


def test_a_partial_image_leaves_out_what_was_not_logged() -> None:
    """MINIMAL logs the key and the changed column only. The rest were not
    observed, which is not the same as NULL, so they are simply absent."""
    minimal = next(e for e in binlog_rows() if e.after == {"note": "checked"})

    assert minimal.before == {"payment_id": 1}


# ── Both sides together ──────────────────────────────────────────────────────


def test_both_tools_now_agree_on_every_column(zone) -> None:
    """Payment 2: the DELETE's before image and the deleted remnant on the page.

    Before these fixes, 4 of its 11 columns disagreed between the tools, and
    the decimals could not even be stored.
    """
    zone("IST-5:30")
    deleted = next(e for e in binlog_rows() if e.event_type == "DELETE").before
    remnant = page_rows(PAGE_DELETED, deleted=True)[0].values

    assert deleted == remnant


def test_decimal_values_can_be_stored(connection, evidence, tool_runs, case_id) -> None:
    """Floats are refused by the store; the Decimals now go in and come back exact."""
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd"))
    events = SqliteBinlogEventRepository(connection)
    records = SqlitePhysicalRecordRepository(connection)

    events.save_many(binlog_rows(), "ev-ibd", "run-1")
    records.save_many(page_rows(PAGE_LIVE), "ev-ibd", "run-1")

    assert events.events()[0].after["amount"] == Decimal("5000.00")
    assert records.records_for("shop", "payments")[0].values["amount"] == Decimal("4000.10")
