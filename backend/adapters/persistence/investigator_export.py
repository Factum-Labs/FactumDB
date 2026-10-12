"""Version-3, bounded-memory report projections. Source evidence is never changed.

Large analysis TEXT columns are read through SQLite's incremental blob API, not
SELECTed into Python. The projection, alias map, reference pool and preview text
live in a disposable SQLite database. Memory is bounded by the largest individual
record/history/transaction, rather than the entire case or analysis stage.
"""

import codecs
import hashlib
import json
import re
import sqlite3
import tempfile
from collections.abc import MutableMapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from adapters.persistence._timestamps import from_text, to_text
from adapters.persistence.export_redaction import POLICY, make_redactor
from adapters.persistence.export_sections import resolve_sections
from core.domain.models.classification import ReconResult
from core.domain.rules import RULES
from core.engine import ANALYSIS_FORMAT_VERSION, ENGINE_REVISION


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class JsonMembers:
    """Incrementally yield (member, index-or-None, value) from a JSON object.

    Arrays are yielded one item at a time, including an explicit empty-array
    marker. JSONDecoder preserves all scalar/tagged values; UTF-8 chunk boundaries
    are handled by an incremental decoder. No regex parses evidence JSON.
    """

    def __init__(self, stream):
        self.stream = stream
        self.buffer = ""
        self.eof = False
        self.utf8 = codecs.getincrementaldecoder("utf-8")()
        self.decoder = json.JSONDecoder()

    def fill(self):
        chunk = self.stream.read(65536)
        self.eof = not chunk
        self.buffer += self.utf8.decode(chunk, final=self.eof)

    def peek(self):
        self.buffer = self.buffer.lstrip()
        while not self.buffer and not self.eof:
            self.fill()
            self.buffer = self.buffer.lstrip()
        return self.buffer[:1]

    def take(self, character):
        if self.peek() != character:
            raise ValueError("Invalid stored analysis JSON")
        self.buffer = self.buffer[1:]

    def value(self):
        self.peek()
        while True:
            try:
                result, end = self.decoder.raw_decode(self.buffer)
                # A scalar number may continue across a read boundary.
                if end == len(self.buffer) and not self.eof:
                    self.fill()
                    continue
                self.buffer = self.buffer[end:]
                return result
            except json.JSONDecodeError:
                if self.eof:
                    raise ValueError("Invalid stored analysis JSON") from None
                self.fill()

    def skip_value(self):
        """Skip an unselected JSON container without allocating its contents."""
        first = self.peek()
        if first not in {"{", "[", '"'}:
            self.value()
            return
        stack = [] if first == '"' else ["}" if first == "{" else "]"]
        quoted = first == '"'
        escaped = False
        self.buffer = self.buffer[1:]
        tokens = re.compile(r'["\\{}\[\]]')
        while True:
            position = 1 if escaped else 0
            escaped = False
            while token := tokens.search(self.buffer, position):
                char = token.group()
                position = token.end()
                if quoted:
                    if char == "\\":
                        escaped = token.end() == len(self.buffer)
                        if not escaped:
                            position += 1
                    elif char == '"':
                        quoted = False
                        if not stack:
                            self.buffer = self.buffer[token.end():]
                            return
                elif char == '"':
                    quoted = True
                elif char in {"{", "["}:
                    stack.append("}" if char == "{" else "]")
                elif char in {"}", "]"}:
                    if not stack or stack.pop() != char:
                        raise ValueError("Invalid stored analysis JSON")
                    if not stack:
                        self.buffer = self.buffer[token.end():]
                        return
            if self.eof:
                raise ValueError("Unterminated stored analysis JSON")
            self.buffer = ""
            self.fill()

    def selected_object(self, fields):
        if self.peek() != "{":
            return self.value()
        self.take("{")
        result = {}
        if self.peek() == "}":
            self.take("}")
            return result
        while True:
            key = self.value()
            self.take(":")
            if key in fields:
                result[key] = self.value()
            else:
                self.skip_value()
            if self.peek() != ",":
                break
            self.take(",")
        self.take("}")
        return result

    def members(self, include=None, item_fields=None):
        self.take("{")
        if self.peek() == "}":
            self.take("}")
            return
        while True:
            member = self.value()
            if not isinstance(member, str):
                raise ValueError("Invalid analysis member")
            self.take(":")
            if include is not None and member not in include:
                self.skip_value()
                if self.peek() != ",":
                    break
                self.take(",")
                continue
            if self.peek() == "[":
                self.take("[")
                if self.peek() == "]":
                    yield member, -1, None
                else:
                    index = 0
                    while True:
                        fields = (item_fields or {}).get(member)
                        value = self.selected_object(fields) if fields is not None else self.value()
                        yield member, index, value
                        index += 1
                        if self.peek() != ",":
                            break
                        self.take(",")
                self.take("]")
            else:
                yield member, None, self.value()
            if self.peek() != ",":
                break
            self.take(",")
        self.take("}")
        if self.peek():
            raise ValueError("Trailing stored analysis data")


class DiskAliases(MutableMapping):
    def __init__(self, db):
        self.db = db
        self._count = db.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]

    def __getitem__(self, key):
        row = self.db.execute("SELECT alias FROM aliases WHERE original=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return row[0]

    def __setitem__(self, key, value):
        inserted = self.db.execute("INSERT OR IGNORE INTO aliases VALUES (?,?)", (key, value))
        if inserted.rowcount:
            self._count += 1
        else:
            self.db.execute("UPDATE aliases SET alias=? WHERE original=?", (value, key))

    def __delitem__(self, key):
        deleted = self.db.execute("DELETE FROM aliases WHERE original=?", (key,))
        if not deleted.rowcount:
            raise KeyError(key)
        self._count -= 1

    def __iter__(self):
        return (row[0] for row in self.db.execute("SELECT original FROM aliases"))

    def __len__(self):
        return self._count


VALUE_MAPS = {"values", "before", "after", "observed_values"}
DISPLAY_FIELDS = {"log_display", "phys_display", "rollup_label", "label"}


class ExportProjection:
    def __init__(self, *, profile, selection, case_id, moment, redacted, settings):
        self.temporary = tempfile.TemporaryDirectory(prefix="factumdb-report-")
        self.db = sqlite3.connect(
            str(Path(self.temporary.name) / "projection.db"), check_same_thread=False
        )
        self.db.executescript("""
            PRAGMA cache_size=-2048;
            PRAGMA temp_store=FILE;
            PRAGMA secure_delete=ON;
            CREATE TABLE entries (name TEXT, ordinal INTEGER, payload TEXT,
                                  PRIMARY KEY(name,ordinal));
            CREATE TABLE tables (name TEXT PRIMARY KEY);
            CREATE TABLE objects (id TEXT PRIMARY KEY, kind TEXT, payload TEXT,
                                  occurrences INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE uses (id TEXT, origin TEXT, occurrences INTEGER,
                               PRIMARY KEY(id,origin));
            CREATE TABLE aliases (original TEXT PRIMARY KEY, alias TEXT);
            CREATE TABLE selected_records (id TEXT, database_name TEXT, table_name TEXT,
                key_columns TEXT, key_values TEXT, PRIMARY KEY(id,database_name,table_name));
            CREATE INDEX selected_record_keys ON selected_records
                (database_name,table_name,key_columns,key_values);
            CREATE TABLE selected_transactions (id TEXT PRIMARY KEY);
            CREATE TABLE selected_sources (evidence_id TEXT, source_file TEXT,
                log_position INTEGER, row_index INTEGER,
                UNIQUE(evidence_id,source_file,log_position,row_index));
            CREATE TABLE stats (name TEXT PRIMARY KEY, included INTEGER DEFAULT 0,
                                summarized INTEGER DEFAULT 0, excluded INTEGER DEFAULT 0);
            CREATE TABLE totals (table_name TEXT, granularity TEXT, result TEXT, count INTEGER,
                                 PRIMARY KEY(table_name,granularity,result));
            CREATE TABLE rules_used (rule_id TEXT PRIMARY KEY);
        """)
        self.profile = profile
        self.selection = selection
        self.sections = set(selection["sections"])
        self.redacted = redacted
        self.visit, self.alias = (
            make_redactor(DiskAliases(self.db)) if redacted else (lambda v: v, lambda v: v)
        )
        self.metadata = {
            "format": "factumdb-case-export",
            "format_version": 3,
            "profile": profile,
            "case_id": self.alias(case_id),
            "exported_at": to_text(moment),
            "engine_revision": ENGINE_REVISION,
            "analysis_format_version": ANALYSIS_FORMAT_VERSION,
            "selection": selection,
            "reference_format": {
                "reference": {"$ref": "object ID"},
                "analysis": "analysis_<stage>_<member> rows preserve index and value; "
                "-1 marks an empty array",
                "note": "Resolve references through objects. Image keys are evidence column names; "
                "only their values can reference pooled evidence values.",
            },
            "presentation": {
                "timezone": settings.get("timezone", "UTC"),
                "examiner_profile": {}
                if redacted or "case_details" not in self.sections
                else settings.get("examiner_profile", {}),
            },
            "limitations": [
                "Custody and processing metadata reflect only recorded observations.",
                "Unknown source locations and missing evidence are not inferred.",
                "FactumDB does not attribute changes to a person or determine intent.",
            ],
        }
        if redacted:
            self.metadata["redaction"] = {
                **POLICY,
                "note": POLICY["note"] + " Unsuitable for independent reanalysis.",
            }
        if profile == "investigator":
            self.metadata["limitations"].append(
                "Summarized investigator report, not the complete evidence dataset."
            )
        self.origin = ""

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
            self.temporary.cleanup()

    def stat(self, name, category, count=1):
        if category not in {"included", "summarized", "excluded"}:
            raise ValueError("Invalid count category")
        self.db.execute("INSERT OR IGNORE INTO stats(name) VALUES (?)", (name,))
        self.db.execute(f"UPDATE stats SET {category}={category}+? WHERE name=?", (count, name))

    def tally(self, table, granularity, result):
        self.db.execute(
            "INSERT INTO totals VALUES (?,?,?,1) ON CONFLICT DO UPDATE SET count=count+1",
            (table, granularity, result),
        )

    def selected_record(self, identifier):
        return (
            self.db.execute("SELECT 1 FROM selected_records WHERE id=?", (identifier,)).fetchone()
            is not None
        )

    def remember_sources(self, value):
        if isinstance(value, list):
            for item in value:
                self.remember_sources(item)
        elif isinstance(value, dict):
            if {"evidence_id", "tool_run_id", "source_file"} <= value.keys():
                self.db.execute(
                    "INSERT OR IGNORE INTO selected_sources VALUES (?,?,?,?)",
                    (
                        value["evidence_id"],
                        value["source_file"],
                        value.get("log_position") if value.get("log_position") is not None else -1,
                        value.get("row_index") if value.get("row_index") is not None else -1,
                    ),
                )
            if value.get("transaction_id"):
                self.db.execute(
                    "INSERT OR IGNORE INTO selected_transactions VALUES (?)",
                    (value["transaction_id"],),
                )
            for key, child in value.items():
                if key not in VALUE_MAPS | {"context", "log", "phys"} or (
                    key == "log" and isinstance(child, list)
                ):
                    self.remember_sources(child)

    def remember_identity(self, record):
        self.db.execute(
            "INSERT OR IGNORE INTO selected_records VALUES (?,?,?,?,?)",
            (
                record["id"],
                record.get("database", ""),
                record.get("table", ""),
                packed(record.get("key_columns", [])),
                packed(record.get("key_values", [])),
            ),
        )

    def intern(self, kind, value):
        payload = packed(value)
        identifier = kind + ":" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.db.execute(
            "INSERT INTO objects(id,kind,payload) VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET occurrences=occurrences+1",
            (identifier, kind, payload),
        )
        self.db.execute(
            "INSERT INTO uses VALUES (?,?,1) ON CONFLICT DO UPDATE SET occurrences=occurrences+1",
            (identifier, self.origin),
        )
        return {"$ref": identifier}

    def normalize(self, value, key=""):
        if key.endswith("rule_id") and isinstance(value, str) and value in RULES:
            self.db.execute("INSERT OR IGNORE INTO rules_used VALUES (?)", (value,))
        if key in {"log", "phys"} and isinstance(value, str) and len(value) > 256:
            return self.intern("value", value)
        if isinstance(value, list):
            return [self.normalize(item, key) for item in value]
        if not isinstance(value, dict):
            return value
        if key in VALUE_MAPS or key in {"context", "arguments"}:
            # User column names can equal structural field names. Never filter
            # or interpret them as report metadata or references.
            if key not in VALUE_MAPS:
                return value
            image = {column: self.evidence_value(child) for column, child in value.items()}
            return self.intern("image", image)
        if any(k.startswith("__") for k in value):
            return value
        kind = None
        if {"record_id", "field", "result", "log", "phys"} <= value.keys():
            kind = "comparison"
        elif {"rule_id", "severity", "subject", "context"} <= value.keys():
            kind = "finding"
        elif {"evidence_id", "tool_run_id", "tool_name", "source_file"} <= value.keys():
            kind = "source"
        elif {"event_type", "database", "table", "log_position", "before", "after"} <= value.keys():
            kind = "event"
        elif {
            "observed_files",
            "gaps",
            "inventory",
        } <= value.keys() or key == "coverage_gaps_touching":
            kind = "coverage"
        elif {"id", "key_columns", "key_values", "database"} <= value.keys():
            kind = "identity"
        elif {"presence", "derived_from", "values"} <= value.keys():
            kind = "state"
        result = {
            k: self.normalize(v, k)
            for k, v in value.items()
            if not (kind in {"comparison", "identity"} and k in DISPLAY_FIELDS)
            and k != "rollup_label"
        }
        return self.intern(kind, result) if kind else result

    def evidence_value(self, value):
        if isinstance(value, str) and len(value) > 256:
            return self.intern("value", value)
        if isinstance(value, list):
            return [self.evidence_value(child) for child in value]
        return value

    def add(self, table, value, *, normalize=True):
        self.origin = table
        value = self.visit(value)
        value = self.normalize(value) if normalize else value
        self.add_prepared(table, value)

    def add_prepared(self, table, value):
        self.db.execute("INSERT OR IGNORE INTO tables VALUES (?)", (table,))
        ordinal = self.db.execute(
            "SELECT COALESCE(MAX(ordinal)+1,0) FROM entries WHERE name=?", (table,)
        ).fetchone()[0]
        self.db.execute("INSERT INTO entries VALUES (?,?,?)", (table, ordinal, packed(value)))

    def collect_findings(self, value):
        if "gaps" not in self.sections:
            return
        if isinstance(value, list):
            for item in value:
                self.collect_findings(item)
        elif isinstance(value, dict):
            if {"rule_id", "severity", "subject", "context"} <= value.keys():
                if value["severity"] != "info" or value["rule_id"].startswith(
                    ("R-COV-", "R-PROV-")
                ):
                    self.remember_sources(value)
                    self.normalize(self.visit(value))
            else:
                for key, child in value.items():
                    if key not in VALUE_MAPS | {"context", "log", "phys"}:
                        self.collect_findings(child)

    def table_names(self):
        return [row[0] for row in self.db.execute("SELECT name FROM tables ORDER BY name")]

    def rows(self, name):
        for row in self.db.execute(
            "SELECT payload FROM entries WHERE name=? ORDER BY ordinal", (name,)
        ):
            yield json.loads(row[0])

    def objects(self):
        for identifier, kind, payload, occurrences in self.db.execute(
            "SELECT * FROM objects ORDER BY id"
        ):
            yield {
                "id": identifier,
                "kind": kind,
                "value": json.loads(payload),
                "occurrences": occurrences,
                "associations": [
                    {"origin": row[0], "occurrences": row[1]}
                    for row in self.db.execute(
                        "SELECT origin,occurrences FROM uses WHERE id=? ORDER BY origin",
                        (identifier,),
                    )
                ],
            }

    def write_json(self, output):
        output.write("{")
        for index, (key, value) in enumerate(self.metadata.items()):
            if index:
                output.write(",")
            output.write(packed(key) + ":" + packed(value))
        output.write(',"tables":{')
        for index, name in enumerate(self.table_names()):
            if index:
                output.write(",")
            output.write(packed(name) + ":[")
            for ordinal, row in enumerate(
                self.db.execute(
                    "SELECT payload FROM entries WHERE name=? ORDER BY ordinal", (name,)
                )
            ):
                if ordinal:
                    output.write(",")
                output.write(row[0])
            output.write("]")
        output.write('},"objects":[')
        for index, obj in enumerate(self.objects()):
            if index:
                output.write(",")
            output.write(packed(obj))
        output.write("]}\n")

    def finish(self):
        # Remove sensitive alias mappings once the frozen projection is built.
        self.metadata["counts"] = {
            row[0]: {"included": row[1], "summarized": row[2], "excluded": row[3]}
            for row in self.db.execute("SELECT * FROM stats ORDER BY name")
        }
        if "reconciliation" in self.sections:
            for (table,) in self.db.execute("SELECT DISTINCT table_name FROM totals"):
                for granularity in ("records", "fields"):
                    for result in ReconResult:
                        self.db.execute(
                            "INSERT OR IGNORE INTO totals VALUES (?,?,?,0)",
                            (table, granularity, result.value),
                        )
            for table, granularity, result, count in self.db.execute(
                "SELECT * FROM totals ORDER BY table_name,granularity,result"
            ):
                # These keys are structural, even when the table identity is aliased.
                self.add_prepared(
                    "reconciliation_totals",
                    {
                        "table": self.alias(table),
                        "granularity": granularity,
                        "result": result,
                        "count": count,
                    },
                )
        for (rule_id,) in self.db.execute("SELECT rule_id FROM rules_used ORDER BY rule_id"):
            definition = RULES.get(rule_id)
            if definition:
                self.add_prepared(
                    "rules",
                    {
                        "rule_id": rule_id,
                        "title": definition.title,
                        "statement": definition.statement,
                        "template": definition.template,
                    },
                )
        self.db.execute("DROP TABLE aliases")
        self.db.commit()
        self.json_size = 0

        class Counter:
            def write(_, text):
                self.json_size += len(text.encode("utf-8"))

        self.write_json(Counter())


def analysis_members(connection, case_id, stage, include=None, item_fields=None):
    row = connection.execute(
        "SELECT rowid,saved_at FROM analysis_results WHERE case_id=? AND stage=?", (case_id, stage)
    ).fetchone()
    if row:
        with connection.blobopen(
            "analysis_results", "result_json", row[0], readonly=True
        ) as stream:
            for member, index, value in JsonMembers(stream).members(
                include=include, item_fields=item_fields
            ):
                if not re.fullmatch(r"[a-z][a-z0-9_]*", member):
                    raise ValueError("Unsupported analysis member")
                yield member, index, value, row[1]


def prepare_projection(connection, case_id, **options):
    steps = prepare_projection_steps(connection, case_id, **options)
    while True:
        try:
            next(steps)
        except StopIteration as completed:
            return completed.value


def prepare_projection_steps(
    connection,
    case_id,
    *,
    profile="investigator",
    sections=None,
    redacted=False,
    preferences=None,
    examiner_profile=None,
    now=None,
):
    from adapters.persistence.case_export import _TABLES, VALUE_TAGS, _row
    from core.application.errors import NotFoundError
    from core.application.preferences import time_label

    if connection.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone() is None:
        raise NotFoundError(f"case not found: {case_id}")
    selection = resolve_sections(profile, sections)
    projection = ExportProjection(
        profile=profile,
        selection=selection,
        case_id=case_id,
        moment=now() if now else datetime.now(UTC),
        redacted=redacted,
        settings={
            "timezone": time_label(preferences) if preferences else "UTC",
            "examiner_profile": examiner_profile or {},
        },
    )
    p = projection
    p.metadata["value_tags"] = dict(VALUE_TAGS)
    try:
        complete = profile == "full"
        s = p.sections
        want_comparisons = "reconciliation" in s
        exact = "exact_matches" in s
        # Reconciliation is scanned first to identify the supporting record set.
        relevant = s & {"reconciliation", "histories", "timeline", "gaps", "intermediate_analysis"}
        reconciliation = analysis_members(connection, case_id, "reconciliation") if relevant else ()
        reconciliation_saved_at = None
        for processed, (member, index, value, saved_at) in enumerate(reconciliation):
            if processed % 32 == 0:
                yield {"stage": "reconciliation", "processed": processed}
            reconciliation_saved_at = saved_at
            p.origin = "analysis_reconciliation_" + member
            p.collect_findings(value)
            if member == "records" and index is not None and index >= 0:
                record = value["record"]
                table = record.get("table", "unknown")
                p.tally(table, "records", value["rollup"])
                fields = value["fields"]
                for field in fields:
                    p.tally(table, "fields", field["result"])
                retained = (
                    [field for field in fields if exact or field["result"] != "Exact"]
                    if want_comparisons
                    else []
                )
                if retained:
                    p.remember_identity(record)
                    p.remember_sources(value)
                    projected = {**value, "fields": retained}
                    p.add(p.origin, {"index": index, "value": projected})
                    p.stat("reconciliation_records", "included")
                else:
                    p.stat(
                        "reconciliation_records", "summarized" if want_comparisons else "excluded"
                    )
                p.stat("reconciliation_fields", "included", len(retained))
                p.stat(
                    "reconciliation_fields",
                    "summarized" if want_comparisons else "excluded",
                    len(fields) - len(retained),
                )
            elif member == "rows":
                # Full exports keep the ordered flat view as references; compact
                # exports already carry each selected field through its record.
                if exact and want_comparisons:
                    p.add(p.origin, {"index": index, "value": value})
            elif want_comparisons or "gaps" in s:
                if (
                    index is None
                    or index == -1
                    or complete
                    or member != "findings"
                    or value.get("severity") != "info"
                ):
                    p.add(p.origin, {"index": index, "value": value})
        if want_comparisons and reconciliation_saved_at is not None:
            p.add(
                "analysis_metadata",
                {"stage": "reconciliation", "saved_at": reconciliation_saved_at},
                normalize=False,
            )

        for stage in ("correlation", "reconstruction", "grouping"):
            stage_section = "timeline" if stage == "grouping" else "histories"
            all_stage = "intermediate_analysis" in s or (
                "complete_histories" in s
                if stage == "reconstruction"
                else "complete_timeline" in s
                if stage == "grouping"
                else False
            )
            stage_values = (
                analysis_members(connection, case_id, stage)
                if (stage_section in s or all_stage or "gaps" in s)
                else ()
            )
            for processed, (member, index, value, _saved_at) in enumerate(stage_values):
                if processed % 32 == 0:
                    yield {"stage": stage, "processed": processed}
                p.origin = f"analysis_{stage}_{member}"
                p.collect_findings(value)
                keep = all_stage
                if stage_section in s and not keep:
                    if index is None or index == -1:
                        keep = True
                    elif member in {"records", "histories"}:
                        keep = p.selected_record(value["record"]["id"])
                    elif member in {"unsupported_tables", "uncertain_tables", "ungrouped_events"}:
                        keep = True
                    elif member == "event_correlations":
                        keep = p.selected_record(value.get("record_id")) or value.get("method") in {
                            "ambiguous",
                            "table_has_no_primary_key",
                            "schema_not_available",
                            "key_columns_not_in_row_image",
                        }
                    elif member == "edges":
                        keep = p.selected_record(value.get("record_id"))
                    elif member == "transactions":
                        keep = (
                            value["status"] != "committed"
                            or p.db.execute(
                                "SELECT 1 FROM selected_transactions WHERE id=?", (value["id"],)
                            ).fetchone()
                            is not None
                        )
                    elif member == "findings":
                        keep = value.get("severity") != "info"
                p.stat(
                    p.origin,
                    "included" if keep else "summarized" if stage_section in s else "excluded",
                )
                if keep:
                    if member in {"records", "histories"} and isinstance(value, dict):
                        p.remember_identity(value["record"])
                    p.remember_sources(value)
                    p.add(p.origin, {"index": index, "value": value})
            if stage_section in s or all_stage:
                saved = connection.execute(
                    "SELECT saved_at FROM analysis_results WHERE case_id=? AND stage=?",
                    (case_id, stage),
                ).fetchone()
                if saved:
                    p.add(
                        "analysis_metadata", {"stage": stage, "saved_at": saved[0]}, normalize=False
                    )

        wanted = {
            "cases": bool(s & {"case_details", "notes"}),
            "evidence_files": "evidence" in s,
            "tool_runs": "tools" in s,
            "integrity_results": "integrity" in s,
            "schemas": "schemas" in s,
            "schema_columns": "schemas" in s,
            "physical_records": "physical_records" in s,
            "binlog_events": "binlog_events" in s,
            "transactions": "timeline" in s,
            "transaction_events": "complete_timeline" in s,
            "warnings": "gaps" in s,
            "binlog_inventory": "evidence" in s,
            "case_scopes": "gaps" in s,
            "normalizations": "gaps" in s,
            "table_creations": "schemas" in s,
            "physical_extractions": "histories" in s,
        }

        @lru_cache(maxsize=256)
        def physical_key_shapes(database, table):
            return tuple(
                columns[0]
                for columns in p.db.execute(
                    "SELECT DISTINCT key_columns FROM selected_records "
                    "WHERE database_name=? AND table_name=?",
                    (database, table),
                )
            )

        for name, sql in _TABLES:
            if name == "analysis_results":
                continue
            if wanted.get(name):
                p.db.execute("INSERT OR IGNORE INTO tables VALUES (?)", (name,))
            has_support = "provenance" in s and (
                (name == "physical_records"
                and p.db.execute("SELECT 1 FROM selected_records LIMIT 1").fetchone())
                or (name == "binlog_events"
                and p.db.execute(
                    "SELECT 1 FROM selected_sources WHERE log_position>=0 LIMIT 1"
                ).fetchone())
            )
            if not wanted.get(name) and not has_support:
                count = connection.execute(
                    "SELECT COUNT(*) FROM (" + sql + ")", (case_id,)
                ).fetchone()[0]
                category = (
                    "summarized"
                    if name in {"physical_records", "binlog_events"} and relevant
                    else "excluded"
                )
                p.stat(name, category, count)
                continue
            for processed, row in enumerate(connection.execute(sql, (case_id,))):
                if processed % 32 == 0:
                    yield {"stage": name, "processed": processed}
                keep = wanted.get(name, False)
                if name in {"schemas", "table_creations"} and keep and "complete_schemas" not in s:
                    keep = (
                        p.db.execute(
                            "SELECT 1 FROM selected_records WHERE database_name=? AND table_name=?",
                            (row["database_name"], row["database_name"] + "." + row["table_name"]),
                        ).fetchone()
                        is not None
                    )
                if name == "schema_columns" and keep and "complete_schemas" not in s:
                    keep = (
                        p.db.execute(
                            "SELECT 1 FROM entries WHERE name='schemas' "
                            "AND json_extract(payload,'$.schema_id')=?",
                            (p.alias(row["schema_id"]),),
                        ).fetchone()
                        is not None
                    )
                if name == "transactions" and keep and "complete_timeline" not in s:
                    keep = (
                        row["status"] != "committed"
                        or p.db.execute(
                            "SELECT 1 FROM selected_transactions WHERE id=?",
                            (row["transaction_id"],),
                        ).fetchone()
                        is not None
                    )
                # Supporting source rows remain checkable without adding ALL raw
                # records/events. Physical locations may be unknown; include all
                # candidates for that evidence rather than invent a unique match.
                if name in {"binlog_events", "physical_records"} and not keep and "provenance" in s:
                    if name == "binlog_events":
                        keep = (
                            p.db.execute(
                                "SELECT 1 FROM selected_sources WHERE evidence_id=? "
                                "AND source_file=? "
                                "AND log_position=? "
                                "AND (row_index=-1 OR row_index=?)",
                                (
                                    row["evidence_id"],
                                    row["source_file"],
                                    row["log_position"],
                                    row["row_index"],
                                ),
                            ).fetchone()
                            is not None
                        )
                    else:
                        from adapters.persistence._values import decode_value
                        from core.domain.models.identity import UnrenderableKey, render_key_value

                        database = row["database_name"]
                        table = database + "." + row["table_name"]
                        values = json.loads(row["values_json"])
                        keep = False
                        for encoded_columns in physical_key_shapes(database, table):
                            columns = json.loads(encoded_columns)
                            if not columns:
                                # No identity to narrow raw rows: retain schema,
                                # counts and limitations, with full rows opt-in.
                                continue
                            try:
                                actual = [
                                    render_key_value(column, decode_value(values[column]))
                                    for column in columns
                                ]
                            except (KeyError, UnrenderableKey):
                                continue
                            if p.db.execute(
                                "SELECT 1 FROM selected_records WHERE database_name=? "
                                "AND table_name=? AND key_columns=? AND key_values=? LIMIT 1",
                                (database, table, encoded_columns, packed(actual)),
                            ).fetchone():
                                keep = True
                                break
                p.stat(
                    name,
                    "included"
                    if keep
                    else "summarized"
                    if name
                    in {
                        "schemas",
                        "schema_columns",
                        "transactions",
                        "physical_records",
                        "binlog_events",
                    }
                    and s & {"schemas", "timeline", "histories", "reconciliation"}
                    else "excluded",
                )
                if not keep:
                    if name == "schemas" and "schemas" in s:
                        key_columns = [
                            column[0]
                            for column in connection.execute(
                                "SELECT name FROM schema_columns WHERE schema_id=? "
                                "AND is_primary_key=1 ORDER BY position",
                                (row["schema_id"],),
                            )
                        ]
                        column_count = connection.execute(
                            "SELECT COUNT(*) FROM schema_columns WHERE schema_id=?",
                            (row["schema_id"],),
                        ).fetchone()[0]
                        p.add(
                            "schema_summaries",
                            {
                                "schema_id": row["schema_id"],
                                "database_name": row["database_name"],
                                "table_name": row["table_name"],
                                "mysql_version_id": row["mysql_version_id"],
                                "column_count": column_count,
                                "primary_key_columns": key_columns,
                                "evidence_id": row["evidence_id"],
                                "tool_run_id": row["tool_run_id"],
                            },
                        )
                    continue
                item = _row(row)
                if name == "cases":
                    if "notes" not in s:
                        item.pop("examiner_notes", None)
                    if "case_details" not in s:
                        item = {k: v for k, v in item.items() if k in {"case_id", "examiner_notes"}}
                if name == "integrity_results" and not complete and item["status"] == "valid":
                    item.pop("raw_summary", None)
                if name == "binlog_events":
                    tool = connection.execute(
                        "SELECT tool_name FROM tool_runs WHERE tool_run_id=?",
                        (item["tool_run_id"],),
                    ).fetchone()
                    source = {
                        "evidence_id": item["evidence_id"],
                        "tool_run_id": item["tool_run_id"],
                        "tool_name": tool[0],
                        "source_file": item["source_file"],
                        "log_position": item["log_position"],
                        "row_index": item["row_index"],
                    }
                    event = {
                        key: item[key]
                        for key in (
                            "event_type",
                            "before",
                            "after",
                            "raw_timestamp",
                            "log_position",
                            "source_file",
                            "gtid",
                            "thread_id",
                            "row_index",
                        )
                    }
                    event.update(
                        database=item["database_name"],
                        table=item["table_name"],
                        provenance=source,
                        timestamp={"__datetime__": from_text(item["event_time_utc"]).isoformat()}
                        if item["event_time_utc"]
                        else None,
                    )
                    item = {
                        "event_id": item["event_id"],
                        "evidence_id": item["evidence_id"],
                        "tool_run_id": item["tool_run_id"],
                        "event": event,
                        "stored_timestamp": item["event_time_utc"],
                    }
                p.add(name, item)
        if (
            "provenance" in s
            and connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='pipeline_runs'"
            ).fetchone()
        ):
            for row in connection.execute(
                "SELECT * FROM pipeline_runs WHERE case_id=? ORDER BY rowid", (case_id,)
            ):
                p.add("pipeline_runs", _row(row))
        yield {"stage": "finalizing selected data", "processed": 0}
        p.finish()
        return p
    except BaseException:
        p.close()
        raise


def expand_document(document):
    """Reference decoder for independent checking of an unredacted v3 export.

    This convenience decoder materializes a document. Export generation never
    uses it. Display strings are intentionally absent, and are not evidence.
    """
    objects = {obj["id"]: obj for obj in document["objects"]}

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"$ref"}:
            obj = objects[value["$ref"]]
            if obj["kind"] == "image":
                return {key: expand(child) for key, child in obj["value"].items()}
            return expand(obj["value"])
        return {
            key: child if key in {"context", "arguments"} else expand(child)
            for key, child in value.items()
        }

    tables = {}
    stages = {}
    saved = {
        row["stage"]: row["saved_at"] for row in document["tables"].get("analysis_metadata", [])
    }
    for name, rows in document["tables"].items():
        if name.startswith("analysis_") and name != "analysis_metadata":
            _, stage, member = name.split("_", 2)
            target = stages.setdefault(stage, {})
            for row in rows:
                value = expand(row["value"])
                if row["index"] is None:
                    target[member] = value
                elif row["index"] == -1:
                    target[member] = []
                else:
                    target.setdefault(member, []).append(value)
        elif name not in {"analysis_metadata", "reconciliation_totals", "rules"}:
            tables[name] = [expand(row) for row in rows]
            if name == "binlog_events":
                restored = []
                for row in tables[name]:
                    event = row["event"]
                    restored.append(
                        {
                            "event_id": row["event_id"],
                            "evidence_id": row["evidence_id"],
                            "tool_run_id": row["tool_run_id"],
                            "database_name": event["database"],
                            "table_name": event["table"],
                            "event_time_utc": row["stored_timestamp"],
                            **{
                                key: value
                                for key, value in event.items()
                                if key not in {"database", "table", "timestamp", "provenance"}
                            },
                        }
                    )
                tables[name] = restored
    tables["analysis_results"] = [
        {
            "case_id": document["case_id"],
            "stage": stage,
            "result": result,
            "saved_at": saved.get(stage),
        }
        for stage, result in stages.items()
    ]
    return {**document, "tables": tables}
