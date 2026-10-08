"""Exporting a case as JSON and CSV, so it can be checked outside FactumDB.

Two formats, for two kinds of reader:

- JSON is the complete, exact record: every table's rows for the case, with
  column values in the same tagged form the database stores them in, so a
  Decimal can never be mistaken for a string. This is the one to check
  against.
- CSV is for opening in a spreadsheet: one file per MySQL table for the rows
  found on the pages and for the binlog changes, with one column per MySQL
  column, plus the evidence, tool runs, warnings and - once the analysis has
  run - the reconciliation results.

Nothing is worked out for the export. It writes what the case database holds,
so every row still carries the evidence file and the tool run it came from,
and anyone can follow a value back to the command that produced it.

An export never overwrites an earlier one. Two exports mixed in one folder
could no longer be told apart.
"""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from adapters.persistence._timestamps import to_text
from adapters.persistence._values import decode_value
from core.application.errors import NotFoundError
from core.domain.models.values import UNOBSERVED, UndecodableValue
from core.engine import ENGINE_REVISION, ANALYSIS_FORMAT_VERSION

FORMAT = "factumdb-case-export"
FORMAT_VERSION = 2

VALUE_TAGS = {
    "__decimal__": "an exact DECIMAL value, written as text so no digit is lost",
    "__datetime__": "a date and time in ISO-8601",
    "__undecodable__": "a value the tool could not decode; the text says why",
    "__unobserved__": "a column the row image did not include",
}

# CSV markers. A CSV cell is only text, so these keep apart things that an
# empty cell would blur together.
NULL = r"\N"                    # SQL NULL, as MySQL itself writes it in exports
NOT_LOGGED = "[not logged]"     # a column a partial row image left out

_THROUGH_EVIDENCE = "JOIN evidence_files e ON e.evidence_id = t.evidence_id WHERE e.case_id = ?"

# Every table, the rows of it that belong to one case, in a fixed order so the
# same case always exports the same way.
_TABLES = (
    ("cases", "SELECT t.* FROM cases t WHERE t.case_id = ?"),
    ("evidence_files",
     "SELECT t.* FROM evidence_files t WHERE t.case_id = ? ORDER BY t.evidence_id"),
    ("tool_runs",
     "SELECT t.* FROM tool_runs t WHERE t.case_id = ? ORDER BY t.started_at, t.tool_run_id"),
    ("integrity_results",
     f"SELECT t.* FROM integrity_results t {_THROUGH_EVIDENCE} ORDER BY t.evidence_id"),
    ("schemas", f"SELECT t.* FROM schemas t {_THROUGH_EVIDENCE} ORDER BY t.schema_id"),
    ("schema_columns",
     "SELECT t.* FROM schema_columns t JOIN schemas s ON s.schema_id = t.schema_id "
     "JOIN evidence_files e ON e.evidence_id = s.evidence_id WHERE e.case_id = ? "
     "ORDER BY t.schema_id, t.position"),
    ("physical_records",
     # Live rows before deleted ones, then in the order they were extracted.
     f"SELECT t.* FROM physical_records t {_THROUGH_EVIDENCE} "
     "ORDER BY t.database_name, t.table_name, t.is_deleted, t.rowid"),
    ("binlog_events",
     f"SELECT t.* FROM binlog_events t {_THROUGH_EVIDENCE} "
     "ORDER BY t.source_file, t.log_position, t.row_index"),
    ("transactions",
     f"SELECT t.* FROM transactions t {_THROUGH_EVIDENCE} ORDER BY t.source_file, t.start_position"),
    ("transaction_events",
     "SELECT t.* FROM transaction_events t JOIN transactions x ON x.transaction_id = t.transaction_id "
     "JOIN evidence_files e ON e.evidence_id = x.evidence_id WHERE e.case_id = ? "
     "ORDER BY t.transaction_id, t.event_order, t.event_id"),
    ("warnings",
     "SELECT t.* FROM warnings t WHERE t.case_id = ? ORDER BY t.created_at, t.rowid"),
    ("binlog_inventory",
     f"SELECT t.* FROM binlog_inventory t {_THROUGH_EVIDENCE} ORDER BY t.evidence_id"),
    ("case_scopes", "SELECT t.* FROM case_scopes t WHERE t.case_id = ?"),
    ("normalizations", "SELECT t.* FROM normalizations t WHERE t.case_id = ?"),
    ("analysis_results",
     "SELECT t.* FROM analysis_results t WHERE t.case_id = ? ORDER BY CASE t.stage "
     "WHEN 'grouping' THEN 1 WHEN 'correlation' THEN 2 WHEN 'reconstruction' THEN 3 ELSE 4 END"),
    ("table_creations", f"SELECT t.* FROM table_creations t {_THROUGH_EVIDENCE} ORDER BY t.source_file, t.log_position"),
    ("physical_extractions", f"SELECT t.* FROM physical_extractions t {_THROUGH_EVIDENCE} ORDER BY t.evidence_id"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── JSON ─────────────────────────────────────────────────────────────────────


def case_export(connection, case_id: str, *, now=_utc_now) -> dict:
    """The whole case as one JSON-ready document."""
    if connection.execute("SELECT 1 FROM cases WHERE case_id = ?", (case_id,)).fetchone() is None:
        raise NotFoundError(f"case not found: {case_id}")
    tables = {
        name: [_row(row) for row in connection.execute(sql, (case_id,)).fetchall()]
        for name, sql in _TABLES
    }
    # Desktop orchestration adds this table to existing case databases. Older
    # standalone databases remain exportable without a migration.
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pipeline_runs'").fetchone():
        tables["pipeline_runs"] = [_row(row) for row in connection.execute(
            "SELECT * FROM pipeline_runs WHERE case_id = ? ORDER BY rowid", (case_id,),
        ).fetchall()]
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "engine_revision": ENGINE_REVISION,
        "analysis_format_version": ANALYSIS_FORMAT_VERSION,
        "case_id": case_id,
        "exported_at": to_text(now()),
        "value_tags": dict(VALUE_TAGS),
        "tables": tables,
    }


def write_json(connection, case_id: str, path, *, now=_utc_now) -> Path:
    document = case_export(connection, case_id, now=now)
    path = Path(path)
    with open(path, "x", encoding="utf-8") as out:      # "x" never overwrites
        json.dump(document, out, indent=2, sort_keys=True, ensure_ascii=False)
        out.write("\n")
    return path


def _row(row) -> dict:
    """A table row, with its *_json columns turned back into JSON."""
    out = {}
    for key in row.keys():
        value = row[key]
        if key.endswith("_json"):
            out[key[:-len("_json")]] = json.loads(value) if value is not None else None
        else:
            out[key] = value
    return out


# ── CSV ──────────────────────────────────────────────────────────────────────


def write_csv(connection, case_id: str, folder, *, now=_utc_now) -> list:
    """One CSV file per kind of data, in a new folder. Returns the files written."""
    tables = case_export(connection, case_id, now=now)["tables"]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)

    written = [
        _write(folder / f"{name}.csv", _header(connection, table), _plain(tables[table]))
        for name, table in (("evidence", "evidence_files"), ("tool_runs", "tool_runs"),
                            ("integrity", "integrity_results"), ("warnings", "warnings"))
    ]
    columns = _columns_by_table(tables)
    written += _row_files(folder, tables["physical_records"], columns)
    written += _event_files(folder, tables["binlog_events"], columns)

    reconciliation = next(
        (r for r in tables["analysis_results"] if r["stage"] == "reconciliation"), None
    )
    if reconciliation is not None:
        written.append(_write(
            folder / "reconciliation.csv",
            ["record_id", "field", "log", "page", "result", "rule_id"],
            _plain([
                {"record_id": f["record_id"], "field": f["field"], "log": f["log_display"],
                 "page": f["phys_display"], "result": f["result"], "rule_id": f["rule_id"]}
                for f in reconciliation["result"]["rows"]
            ]),
        ))

    (folder / "about.txt").write_text(
        f"Format version: {FORMAT_VERSION}; engine revision: {ENGINE_REVISION}; "
        f"analysis format version: {ANALYSIS_FORMAT_VERSION}\n\n" + _ABOUT, encoding="utf-8",
    )
    return written


def _row_files(folder, records, columns):
    """rows_<db>.<table>.csv - the rows on the pages, live and deleted."""
    written = []
    for (database, table), group in _by_table(records).items():
        names = columns.get((database, table)) or _all_keys(r["values"] for r in group)
        header = ["record_id", "evidence_id", "tool_run_id", "is_deleted", *names]
        rows = [
            {**{key: _cell(r[key]) for key in header[:4]},
             **{name: _value_cell(r["values"][name]) if name in r["values"] else ""
                for name in names}}
            for r in group
        ]
        written.append(_write(folder / f"rows_{_safe(database)}.{_safe(table)}.csv", header, rows))
    return written


_EVENT_FIELDS = ("event_id", "source_file", "log_position", "row_index", "event_type",
                 "event_time_utc", "raw_timestamp", "gtid", "thread_id", "tool_run_id")


def _event_files(folder, events, columns):
    """events_<db>.<table>.csv - every row change, before and after."""
    written = []
    for (database, table), group in _by_table(events).items():
        names = columns.get((database, table)) or _all_keys(
            image for e in group for image in (e["before"], e["after"]) if image
        )
        header = [*_EVENT_FIELDS, *(f"{side}.{name}" for side in ("before", "after") for name in names)]
        rows = [
            {**{key: _cell(e[key]) for key in _EVENT_FIELDS},
             **{f"{side}.{name}": _image_cell(e[side], name)
                for side in ("before", "after") for name in names}}
            for e in group
        ]
        written.append(_write(folder / f"events_{_safe(database)}.{_safe(table)}.csv", header, rows))
    return written


def _columns_by_table(tables):
    """(database, table) -> its column names in schema order."""
    schema_tables = {s["schema_id"]: (s["database_name"], s["table_name"]) for s in tables["schemas"]}
    by_schema = defaultdict(list)
    for column in tables["schema_columns"]:
        by_schema[column["schema_id"]].append(column["name"])   # already in position order
    columns = {}
    for schema_id, names in by_schema.items():
        columns.setdefault(schema_tables[schema_id], names)
    return columns


def _header(connection, table):
    """A table's column names as the export names them, for a file even with no rows."""
    names = [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
    return [name[:-len("_json")] if name.endswith("_json") else name for name in names]


def _by_table(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["database_name"], row["table_name"])].append(row)
    return dict(sorted(grouped.items()))


def _all_keys(dicts):
    return sorted({key for d in dicts for key in d})


def _plain(rows):
    return [{key: _cell(value) for key, value in row.items()} for row in rows]


def _image_cell(image, name):
    if image is None:
        return ""                # the event has no such image (INSERT before, DELETE after)
    if name not in image:
        return NOT_LOGGED
    return _value_cell(image[name])


def _value_cell(stored):
    """A MySQL column value, from its stored tagged form, as CSV text."""
    value = decode_value(stored)
    if value is None:
        return NULL
    if value is UNOBSERVED:
        return NOT_LOGGED
    if isinstance(value, UndecodableValue):
        return f"[undecodable: {value.reason}]"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return _defused(value)
    return str(value)            # int, and Decimal as its exact text


def _cell(value):
    """Any other field: ids, hashes, paths, messages."""
    if value is None:
        return NULL
    if isinstance(value, (dict, list)):
        return _defused(json.dumps(value, sort_keys=True, ensure_ascii=False))
    if isinstance(value, str):
        return _defused(value)
    return str(value)


def _defused(text):
    """Stop a spreadsheet from running text from the evidence as a formula.

    A cell starting with = + - @ (or a tab or carriage return) is treated as a
    formula by Excel and LibreOffice. The evidence comes from a database that
    may have been tampered with, so its text cannot be trusted not to contain
    one. A leading quote makes the spreadsheet show the text instead.
    """
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _write(path, header, rows):
    """Rows are dicts of finished cell text, in header order."""
    with open(path, "x", newline="", encoding="utf-8") as out:   # "x" never overwrites
        writer = csv.writer(out)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row[name] for name in header])
    return path


def _safe(name):
    """A MySQL name made safe to use in a file name."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


_ABOUT = """\
FactumDB case export (CSV)

These files are for reading the case in a spreadsheet. The JSON export of the
same case is the exact, complete record and is the one to check against.

Markers used in the cells:
  \\N                    SQL NULL
  [not logged]          a column a partial row image (binlog_row_image=MINIMAL) left out
  [undecodable: ...]    a value the tool could not decode; the text says why
  (empty)               in events_*.csv: the event has no such image
                        (an INSERT has no before image, a DELETE no after image)

Text that starts with = + - @ is shown with a leading ' so a spreadsheet does
not run it as a formula. The evidence may have been tampered with, so its text
is never trusted to be harmless.

Every row keeps the evidence_id and tool_run_id it came from; tool_runs.csv
shows the exact command, tool version and executable hash behind each run.
"""
