"""Adapter for mysqlbinlog.

mysqlbinlog decodes a binary log into text. With -v -v and
--base64-output=DECODE-ROWS it prints the actual row changes as comments:

    #260904 20:06:38 server id 1  end_log_pos 1112 ...  Update_rows: table id 89
    ### UPDATE `finance`.`accounts`
    ### WHERE
    ###   @1=101 /* INT meta=0 nullable=0 is_null=0 */
    ###   @3=5000 /* INT meta=0 nullable=1 is_null=0 */
    ### SET
    ###   @1=101 /* INT meta=0 nullable=0 is_null=0 */
    ###   @3=4000 /* INT meta=0 nullable=1 is_null=0 */

This is a line by line state machine over that text. The parts it tracks:

  - the event header, which carries the time and the end_log_pos
  - SET @@SESSION.GTID_NEXT, which gives the GTID of the transaction
  - Table_map, which says which table a numeric table id refers to
  - Write_rows / Update_rows / Delete_rows, which start a row event
  - the ### lines, which carry the before and after images
  - Xid and COMMIT / ROLLBACK, which close a transaction

Two things need care.

Columns are numbered, not named. mysqlbinlog only ever says @1, @2, @3, and
those numbers count visible columns only. Turning them into names is this
adapter's job, which is why it needs a schema lookup. If no schema is
available for a table the event is skipped and a warning is recorded, because
storing a value under the wrong column name would be a false statement about
the evidence.

Times are printed in the server's local timezone with no marker on them. The
offset is not guessed: mysqlbinlog prints it in the commit timestamp comment,
"original_commit_timestamp=... (2026-09-04 20:06:38.761046 +0530)", so the
offset is read from the log itself and used to convert the header times to
UTC. The original text is kept in raw_timestamp either way.
"""

import re
import subprocess
from datetime import datetime, timedelta, timezone

from core.domain.models.canonical import BinlogEvent, TransactionMarker
from core.domain.models.values import UndecodableValue
from core.domain.models.canonical import AnalysisWarning

# "#260904 20:06:38 server id 1  end_log_pos 1112" - note the hour can be a
# single digit, as in "#260816  0:36:25".
HEADER = re.compile(
    r"^#(\d{6})\s+(\d{1,2}:\d{2}:\d{2})\s+server id \d+\s+end_log_pos (\d+)"
)
GTID_NEXT = re.compile(r"SET @@SESSION\.GTID_NEXT=\s*'([^']+)'")
COMMIT_TS = re.compile(r"original_commit_timestamp=\d+\s+\([^)]*?([+-]\d{4})\)")
THREAD_ID = re.compile(r"thread_id=(\d+)")
XID = re.compile(r"\bXid = (\d+)")
TABLE_MAP = re.compile(r"Table_map:\s*`([^`]+)`\.`([^`]+)`\s+mapped to number (\d+)")
ROW_EVENT = re.compile(r"\b(Write_rows|Update_rows|Delete_rows):\s*table id (\d+)")
ROW_START = re.compile(r"^###\s+(INSERT INTO|UPDATE|DELETE FROM)\s+`([^`]+)`\.`([^`]+)`")
FIELD = re.compile(r"^###\s+@(\d+)=(.*?)(?:\s*/\*.*\*/)?\s*$")

OPERATION = {
    "Write_rows": "INSERT",
    "Update_rows": "UPDATE",
    "Delete_rows": "DELETE",
}


class MysqlBinlogAdapter:
    """Decodes one binary log file into row events and transaction markers."""

    def __init__(self, mysqlbinlog_path="mysqlbinlog"):
        self.mysqlbinlog_path = mysqlbinlog_path

    def decode(self, binlog_path, schema_lookup):
        """Run mysqlbinlog on one file and parse what it prints.

        schema_lookup(database, table) should return a Schema or None.
        Returns (events, markers, warnings).
        """
        command = [
            self.mysqlbinlog_path, "-v", "-v",
            "--base64-output=DECODE-ROWS", binlog_path,
        ]
        result = subprocess.run(command, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"mysqlbinlog failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace')[:300]}"
            )
        source_file = binlog_path.split("/")[-1]
        return self.parse(
            result.stdout.decode(errors="replace"), source_file, schema_lookup
        )

    @staticmethod
    def parse(text, source_file, schema_lookup):
        """Walk the decoded text and build events and markers.

        Kept separate from decode() so it can be run against saved output.
        """
        state = _ParserState(source_file, schema_lookup)

        for line in text.splitlines():
            state.feed(line)

        state.finish()
        return state.events, state.markers, state.warnings


class _ParserState:
    """Everything the line by line walk has to remember as it goes."""

    def __init__(self, source_file, schema_lookup):
        self.source_file = source_file
        self.schema_lookup = schema_lookup

        self.events = []
        self.markers = []
        self.warnings = []

        # Read from the log rather than assumed. Stays None until the first
        # commit timestamp comment, and then times are converted with it.
        self.tz = None

        self.table_map = {}        # numeric table id -> (database, table)
        self.gtid = None
        self.thread_id = None
        self.timestamp = None      # datetime of the current event
        self.raw_timestamp = ""
        self.log_position = 0

        # The row event currently being read.
        self.operation = None
        self.database = None
        self.table = None
        self.image = None          # "before" or "after"
        self.before = None
        self.after = None

        # The transaction currently open.
        self.txn_open = False
        self.txn_start = 0
        self.txn_gtid = None
        self.txn_thread_id = None
        self.txn_positions = []

    # -- the main dispatch ------------------------------------------------

    def feed(self, line):
        if line.startswith("###"):
            self._feed_row_line(line)
            return

        # Any non-### line ends whatever row image was being read.
        self._flush_row()

        header = HEADER.match(line)
        if header:
            self._read_header(header)

        offset = COMMIT_TS.search(line)
        if offset and self.tz is None:
            self.tz = _offset_to_timezone(offset.group(1))

        gtid = GTID_NEXT.search(line)
        if gtid and gtid.group(1) != "AUTOMATIC":
            self.gtid = gtid.group(1)

        thread = THREAD_ID.search(line)
        if thread:
            self.thread_id = int(thread.group(1))

        table_map = TABLE_MAP.search(line)
        if table_map:
            database, table, table_id = table_map.groups()
            self.table_map[table_id] = (database, table)

        row_event = ROW_EVENT.search(line)
        if row_event:
            kind, table_id = row_event.groups()
            self.operation = OPERATION[kind]
            self.database, self.table = self.table_map.get(table_id, (None, None))

        if line.strip() == "BEGIN":
            self._open_transaction()

        xid = XID.search(line)
        if xid:
            self._close_transaction("committed", int(xid.group(1)))
        elif line.startswith("ROLLBACK"):
            self._close_transaction("rolled_back", None)

    def finish(self):
        """Called at the end of the file."""
        self._flush_row()
        if self.txn_open:
            # The file ended in the middle of a transaction. That is a real
            # evidence gap, so it is recorded rather than dropped.
            self._close_transaction("incomplete", None)

    # -- the ### row image lines -----------------------------------------

    def _feed_row_line(self, line):
        start = ROW_START.match(line)
        if start:
            # A new row inside the same event - flush the previous one.
            self._flush_row()
            _, database, table = start.groups()
            self.database, self.table = database, table
            self.before = None
            self.after = None
            self.image = None
            return

        stripped = line[3:].strip()
        if stripped == "WHERE":
            self.image = "before"
            self.before = {}
            return
        if stripped == "SET":
            self.image = "after"
            self.after = {}
            return

        field = FIELD.match(line)
        if field and self.image:
            position = int(field.group(1))
            value = _convert_field(field.group(2))
            target = self.before if self.image == "before" else self.after
            target[position] = value

    def _flush_row(self):
        """Turn the collected images into a BinlogEvent, if there is one."""
        if self.before is None and self.after is None:
            return
        if not self.operation or not self.database or not self.table:
            self._reset_row()
            return

        schema = self.schema_lookup(self.database, self.table)
        if schema is None:
            self.warnings.append(AnalysisWarning(
                code="SCHEMA_NOT_FOUND",
                message=(
                    f"No schema for {self.database}.{self.table}, so the @N "
                    f"columns in this event could not be named."
                ),
                context={
                    "database": self.database,
                    "table": self.table,
                    "source_file": self.source_file,
                    "log_position": str(self.log_position),
                },
            ))
            self._reset_row()
            return

        event = BinlogEvent(
            event_type=self.operation,
            database=self.database,
            table=self.table,
            before=self._name_columns(schema, self.before),
            after=self._name_columns(schema, self.after),
            timestamp=self.timestamp,
            raw_timestamp=self.raw_timestamp,
            log_position=self.log_position,
            source_file=self.source_file,
            gtid=self.gtid,
            thread_id=self.thread_id,
        )
        self.events.append(event)
        if self.txn_open:
            self.txn_positions.append(self.log_position)
        self._reset_row()

    def _name_columns(self, schema, image):
        """Turn {1: value, 2: value} into {"account_id": value, ...}.

        None stays None: an INSERT has no before image and a DELETE has no
        after image, and that is different from a column being NULL.
        """
        if image is None:
            return None

        named = {}
        for position, value in sorted(image.items()):
            column = schema.column_by_position(position) if hasattr(
                schema, "column_by_position") else _column_at(schema, position)
            if column is None:
                self.warnings.append(AnalysisWarning(
                    code="COLUMN_POSITION_UNKNOWN",
                    message=(
                        f"@{position} has no matching column in "
                        f"{schema.database}.{schema.table}."
                    ),
                    context={"position": str(position),
                             "table": f"{schema.database}.{schema.table}"},
                ))
                continue
            named[column.name] = value
        return named

    def _reset_row(self):
        self.before = None
        self.after = None
        self.image = None

    # -- headers and transactions -----------------------------------------

    def _read_header(self, match):
        day, clock, position = match.groups()
        self.raw_timestamp = f"{day} {clock}"
        self.log_position = int(position)

        naive = datetime.strptime(f"{day} {clock}", "%y%m%d %H:%M:%S")
        if self.tz is None:
            # No offset seen yet. Reading it as UTC is the honest default -
            # in practice MySQL 8 prints the offset before any row event.
            self.timestamp = naive.replace(tzinfo=timezone.utc)
        else:
            self.timestamp = naive.replace(tzinfo=self.tz).astimezone(timezone.utc)

    def _open_transaction(self):
        self.txn_open = True
        self.txn_start = self.log_position
        self.txn_gtid = self.gtid
        self.txn_thread_id = self.thread_id
        self.txn_positions = []

    def _close_transaction(self, status, xid):
        if not self.txn_open:
            return
        self.markers.append(TransactionMarker(
            status=status,
            start_position=self.txn_start,
            end_position=self.log_position,
            source_file=self.source_file,
            event_positions=tuple(self.txn_positions),
            gtid=self.txn_gtid,
            xid=xid,
            thread_id=self.txn_thread_id,
        ))
        self.txn_open = False
        self.txn_positions = []


def _column_at(schema, position):
    """Fallback when the Schema has no column_by_position helper."""
    for column in schema.columns:
        if column.position == position:
            return column
    return None


def _offset_to_timezone(text):
    """Turn "+0530" into a timezone."""
    sign = 1 if text[0] == "+" else -1
    hours = int(text[1:3])
    minutes = int(text[3:5])
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _convert_field(raw):
    """Turn the text after @N= into a Python value."""
    raw = raw.strip()
    if raw == "" or raw.upper() == "NULL":
        return None

    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")

    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass

    # mysqlbinlog prints some types in forms we do not decode yet, for example
    # binary data as hex. Keeping the raw text would look like a real value, so
    # it is marked instead.
    return UndecodableValue(f"unrecognised binlog value: {raw[:40]}")
