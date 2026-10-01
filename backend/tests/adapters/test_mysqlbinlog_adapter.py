"""The binlog parser's transaction markers.

The persistence layer turns every position a marker lists into a link to a
stored event, so these tests pin down exactly which positions a marker lists.
"""

from __future__ import annotations

from adapters.tools.mysqlbinlog_adapter import MysqlBinlogAdapter
from core.domain.models.canonical import Column, Schema

ACCOUNTS = Schema(
    database="finance",
    table="accounts",
    columns=(
        Column("account_id", 1, "int", False, True),
        Column("status", 2, "varchar(20)", True, False),
    ),
    mysql_version_id=80410,
)

# One transaction: a two-row UPDATE at 1600, then a one-row DELETE from a
# table with no schema at 1700.
TEXT = """\
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
#260923 12:00:00 server id 1  end_log_pos 1650 CRC32 0x4 \tTable_map: `finance`.`audit` mapped to number 90
#260923 12:00:00 server id 1  end_log_pos 1700 CRC32 0x5 \tDelete_rows: table id 90 flags: STMT_END_F
### DELETE FROM `finance`.`audit`
### WHERE
###   @1=7 /* INT meta=0 nullable=0 is_null=0 */
#260923 12:00:00 server id 1  end_log_pos 1731 CRC32 0x6 \tXid = 50
COMMIT/*!*/;
"""


def parse():
    def lookup(database, table):
        return ACCOUNTS if (database, table) == ("finance", "accounts") else None

    return MysqlBinlogAdapter.parse(TEXT, "mysql-bin.000024", lookup)


def test_a_multi_row_event_is_listed_once_in_its_marker() -> None:
    """Two row images, one binlog event, so one position."""
    events, markers, _ = parse()

    assert [e.log_position for e in events] == [1600, 1600]
    assert markers[0].event_positions == (1600,)


def test_a_skipped_event_is_not_listed_in_its_marker() -> None:
    """With no schema the DELETE is skipped and a warning is raised instead.

    The marker must not list it either, or the transaction would claim an
    event that was never emitted and could never be stored.
    """
    _, markers, warnings = parse()

    assert 1700 not in markers[0].event_positions
    assert [w.code for w in warnings] == ["SCHEMA_NOT_FOUND"]
