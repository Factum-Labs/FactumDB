"""Disk-backed, grouped investigator summaries. No record values enter the PDF."""

from collections import OrderedDict
import hashlib
import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from adapters.persistence._timestamps import to_text
from adapters.persistence.case_export import _row
from adapters.persistence.export_redaction import POLICY, examiner_metadata, make_redactor
from adapters.persistence.investigator_export import (
    STREAM_PROGRESS,
    DiskAliases,
    analysis_members,
    packed,
)
from core.application.errors import NotFoundError
from core.domain.models.classification import ReconResult
from core.domain.rules import RULES
from core.engine import ANALYSIS_FORMAT_VERSION, ENGINE_REVISION

TEMPLATE_VERSION = "investigator-summary-6"
CLASSIFICATIONS = tuple(result.value for result in ReconResult)
EXCEPTIONS = set(CLASSIFICATIONS) - {"Exact", "Strong"}


def export_definitions():
    return [
        {
            "format": "JSON",
            "title": "Full case JSON",
            "detail": "full",
            "description": "Every unique observation and complete analysis, "
            "including Exact and Strong.",
        },
        {
            "format": "PDF",
            "title": "Investigator summary PDF",
            "detail": "summary",
            "description": "Evidence, classification totals and grouped findings; "
            "no individual records.",
        },
    ]


def digest(value):
    return hashlib.sha256(packed(value).encode("utf-8")).hexdigest()


def position(value):
    if isinstance(value, bool):
        return -1
    if isinstance(value, int):
        return value if value >= 0 else -1
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return -1


def sources(value):
    if isinstance(value, list):
        for child in value:
            yield from sources(child)
    elif isinstance(value, dict):
        if {"evidence_id", "tool_run_id", "source_file"} <= value.keys():
            yield value
        else:
            for key, child in value.items():
                if key not in {"context", "values", "before", "after", "phys"}:
                    yield from sources(child)


class SummaryProjection:
    def __init__(self, case_id, *, redacted, moment, settings):
        self.temporary = tempfile.TemporaryDirectory(prefix="factumdb-summary-")
        self.db = sqlite3.connect(Path(self.temporary.name) / "summary.db", check_same_thread=False)
        self.db.executescript("""
            PRAGMA cache_size=-2048;
            PRAGMA temp_store=FILE;
            PRAGMA secure_delete=ON;
            CREATE TABLE aliases(original TEXT PRIMARY KEY, alias TEXT);
            CREATE TABLE entries(section TEXT, ordinal INTEGER, payload TEXT,
                                 PRIMARY KEY(section,ordinal));
            CREATE TABLE totals(table_name TEXT, granularity TEXT, result TEXT, count INTEGER,
                                PRIMARY KEY(table_name,granularity,result));
            CREATE TABLE groups(id TEXT PRIMARY KEY, kind TEXT, table_name TEXT, field TEXT,
                                result TEXT, rule_id TEXT, severity TEXT, evidence_id TEXT,
                                occurrences INTEGER DEFAULT 0);
            CREATE TABLE members(group_id TEXT, record_id TEXT, PRIMARY KEY(group_id,record_id));
            CREATE TABLE occurrences(group_id TEXT, identity TEXT, context TEXT,
                                     PRIMARY KEY(group_id,identity));
            CREATE TABLE refs(group_id TEXT, evidence_id TEXT, tool_run_id TEXT, source_file TEXT,
                              position INTEGER, row_index INTEGER,
                              PRIMARY KEY(group_id,evidence_id,tool_run_id,
                                          source_file,position,row_index));
            CREATE TABLE unknown_refs(group_id TEXT, observation TEXT, evidence_id TEXT,
                tool_run_id TEXT, source_file TEXT,
                PRIMARY KEY(group_id,observation,evidence_id,tool_run_id,source_file));
            CREATE TABLE seen_inputs(category TEXT, identity TEXT, PRIMARY KEY(category,identity));
            CREATE TABLE counters(section TEXT, table_name TEXT, label TEXT, count INTEGER,
                                  PRIMARY KEY(section,table_name,label));
            CREATE TABLE record_tables(record_id TEXT PRIMARY KEY, table_name TEXT);
        """)
        self._totals = {}
        self._counters = {}
        self._group_ids = OrderedDict()
        self._seen_groups = OrderedDict()
        self._ordinals = {}
        self.redacted = redacted
        self.visit, self.alias = (
            make_redactor(DiskAliases(self.db), typed=True)
            if redacted
            else (lambda value, **kwargs: value, lambda value, category="VALUE": value)
        )
        self.metadata = {
            "case_id": case_id,
            "exported_at": to_text(moment),
            "engine_revision": ENGINE_REVISION,
            "analysis_format_version": ANALYSIS_FORMAT_VERSION,
            "template_version": TEMPLATE_VERSION,
            "timezone": settings.get("preferences", {}).get("time_mode", "utc"),
            "examiner_profile": examiner_metadata(settings.get("examiner_profile", {}))
            if redacted
            else settings.get("examiner_profile", {}),
            "limitations": [
                "Summary report: complete observations and analysis details "
                "are in the full case JSON.",
                "Exact and Strong comparisons are counts only. No individual records are listed.",
                "Custody information reflects recorded observations; "
                "unrecorded transfers are not inferred.",
                "Unknown source locations remain unknown. "
                "FactumDB does not determine intent or attribution.",
                "Finding groups may overlap; distinct record counts "
                "must not be added across groups.",
            ],
        }
        if redacted:
            self.metadata["redaction"] = POLICY["note"] + " Unsuitable for independent reanalysis."
        self.pdf_path = Path(self.temporary.name) / "summary.pdf"
        self.pdf_size = 0
        self.pages = 0

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
            self.temporary.cleanup()

    def add(self, section, value, *, redact=True):
        ordinal = self.db.execute(
            "SELECT COALESCE(MAX(ordinal)+1,0) FROM entries WHERE section=?", (section,)
        ).fetchone()[0]
        rendered = self.visit(value, section=section) if redact else value
        if redact:
            if section == "coverage_gaps" and value.get("reason") in {
                "missing_file",
                "truncated_file",
                "no_index",
            }:
                rendered["reason"] = value["reason"]
            for key, original in value.items():
                if (original is None or original == "") and key in {
                    "source_path",
                    "source_file",
                    "acquisition_method",
                    "actor_id",
                    "actor_username",
                    "tool_version",
                    "examiner",
                    "examiner_notes",
                    "working_copy_sha256",
                    "first_run",
                    "last_run",
                    "after_file",
                    "before_file",
                }:
                    rendered[key] = None
        self.db.execute(
            "INSERT INTO entries VALUES (?,?,?)",
            (
                section,
                ordinal,
                packed(rendered),
            ),
        )

    def rows(self, section):
        for row in self.db.execute(
            "SELECT payload FROM entries WHERE section=? ORDER BY ordinal", (section,)
        ):
            yield json.loads(row[0])

    def table_label(self, table):
        return table if table in {"Unknown", "Case / unknown table"} else self.alias(table, "TABLE")

    def _flush_counts(self):
        self.db.executemany(
            "INSERT INTO totals VALUES (?,?,?,?) ON CONFLICT DO UPDATE SET count=count+excluded.count",
            ((*key, count) for key, count in self._totals.items()),
        )
        self.db.executemany(
            "INSERT INTO counters VALUES (?,?,?,?) ON CONFLICT DO UPDATE SET count=count+excluded.count",
            ((*key, count) for key, count in self._counters.items()),
        )
        self._totals.clear(); self._counters.clear()

    def tally(self, table, granularity, result):
        key = (table, granularity, result)
        self._totals[key] = self._totals.get(key, 0) + 1
        if len(self._totals) > 512:
            self._flush_counts()

    def count(self, section, table, label, amount=1):
        key = (section, table, label)
        self._counters[key] = self._counters.get(key, 0) + amount
        if len(self._counters) > 512:
            self._flush_counts()

    def group(
        self,
        *,
        kind,
        table="Unknown",
        field="",
        result="",
        rule_id,
        severity="warning",
        evidence_id="",
        record_id=None,
        identity=None,
        context=None,
        provenance=(),
    ):
        key = (kind, table, field, result, rule_id, severity, evidence_id)
        identifier = self._group_ids.get(key)
        if identifier is None:
            identifier = digest(key)
            self.db.execute(
                "INSERT OR IGNORE INTO groups(id,kind,table_name,field,result,rule_id,"
                "severity,evidence_id) VALUES (?,?,?,?,?,?,?,?)", (identifier, *key),
            )
            self._group_ids[key] = identifier
            if len(self._group_ids) > 512:
                self._group_ids.popitem(last=False)
        else:
            self._group_ids.move_to_end(key)
        refs = list(sources(provenance))
        context_hash = digest(context)
        observation_identity = identity or context_hash
        observation = (identifier, observation_identity, context_hash, record_id, digest(refs))
        if observation in self._seen_groups:
            self._seen_groups.move_to_end(observation)
            return identifier
        self._seen_groups[observation] = True
        if len(self._seen_groups) > 2048:
            self._seen_groups.popitem(last=False)
        # Count logical observations, not their repeated nested presentation copies.
        inserted = self.db.execute(
            "INSERT OR IGNORE INTO occurrences VALUES (?,?,?)",
            (identifier, observation_identity, context_hash),
        )
        if inserted.rowcount:
            self.db.execute("UPDATE groups SET occurrences=occurrences+1 WHERE id=?", (identifier,))
        if record_id:
            self.db.execute("INSERT OR IGNORE INTO members VALUES (?,?)", (identifier, record_id))
        if not refs:
            refs = [
                {
                    "evidence_id": evidence_id or "Unknown",
                    "tool_run_id": "Unknown",
                    "source_file": "Unknown",
                }
            ]
        for ref in refs:
            self.db.execute(
                "INSERT OR IGNORE INTO refs VALUES (?,?,?,?,?,?)",
                (
                    identifier,
                    ref.get("evidence_id") or "Unknown",
                    ref.get("tool_run_id") or "Unknown",
                    ref.get("source_file") or "Unknown",
                    position(ref.get("log_position")),
                    position(ref.get("row_index")),
                ),
            )
            if position(ref.get("log_position")) == -1:
                self.db.execute(
                    "INSERT OR IGNORE INTO unknown_refs VALUES (?,?,?,?,?)",
                    (
                        identifier,
                        observation_identity,
                        ref.get("evidence_id") or "Unknown",
                        ref.get("tool_run_id") or "Unknown",
                        ref.get("source_file") or "Unknown",
                    ),
                )
        return identifier

    def finding(self, value):
        rule = value.get("rule_id", "Unknown")
        severity = value.get("severity", "warning")
        if severity == "info" and not rule.startswith(("R-COV-", "R-PROV-")):
            return
        context = value.get("context", {})
        subject = value.get("subject", {})
        record_id = context.get("record") or (
            subject.get("id") if subject.get("kind") == "record" else None
        )
        table = context.get("table") or context.get("qualified_table")
        if not table and record_id:
            row = self.db.execute(
                "SELECT table_name FROM record_tables WHERE record_id=?", (record_id,)
            ).fetchone()
            table = row[0] if row else None
        if not table and subject.get("kind") == "table":
            table = subject.get("id")
        refs = list(sources(value.get("provenance", [])))
        evidence = sorted({ref.get("evidence_id") or "Unknown" for ref in refs}) or ["Unknown"]
        # Group a multi-source observation once; the source summaries retain each association.
        self.group(
            kind="warning",
            table=table or "Case / unknown table",
            rule_id=rule,
            severity=severity,
            evidence_id=" + ".join(evidence),
            record_id=record_id,
            identity=digest(value),
            context=context,
            provenance=refs,
        )

    def finish(self):
        self._flush_counts()
        self.metadata["classification_totals"] = {
            granularity: {
                result: self.db.execute(
                    "SELECT COALESCE(SUM(count),0) FROM totals WHERE granularity=? AND result=?",
                    (granularity, result),
                ).fetchone()[0]
                for result in CLASSIFICATIONS
            }
            for granularity in ("records", "fields")
        }
        for table, granularity, result, count in self.db.execute(
            "SELECT * FROM totals ORDER BY table_name,granularity,result"
        ):
            self.add(
                "classification_tables",
                {
                    "table": self.table_label(table),
                    "granularity": granularity,
                    "result": result,
                    "count": count,
                },
                redact=False,
            )
        for section, table, label, count in self.db.execute(
            "SELECT * FROM counters ORDER BY section,table_name,label"
        ):
            self.add(
                section,
                {
                    "table": self.table_label(table) if table else "Case",
                    "category": label,
                    "count": count,
                },
                redact=False,
            )
        groups = self.db.execute(
            "SELECT * FROM groups ORDER BY "
            "CASE result WHEN 'Conflicting' THEN 0 WHEN 'Unresolved' THEN 1 "
            "WHEN 'Partial' THEN 2 WHEN 'Unsupported' THEN 3 ELSE 4 END,"
            "table_name,field,rule_id,severity,evidence_id"
        )
        for (
            identifier,
            kind,
            table,
            field,
            result,
            rule,
            severity,
            _evidence,
            occurrences,
        ) in groups:
            record_count = self.db.execute(
                "SELECT COUNT(*) FROM members WHERE group_id=?", (identifier,)
            ).fetchone()[0]
            contexts = self.db.execute(
                "SELECT COUNT(DISTINCT context) FROM occurrences WHERE group_id=?", (identifier,)
            ).fetchone()[0]
            definition = RULES.get(rule)
            self.add(
                "warnings" if kind == "warning" else "findings",
                {
                    "table": self.table_label(table),
                    "field": (
                        field if kind == "record" else self.alias(field, "FIELD") if field else ""
                    ),
                    "result": result,
                    "rule_id": rule,
                    "severity": severity,
                    "title": definition.title if definition else rule.replace("_", " "),
                    "explanation": definition.statement
                    if definition
                    else "Recorded warning category. Complete diagnostic messages "
                    "are retained in JSON.",
                    "records": record_count,
                    "occurrences": occurrences,
                    "contexts": contexts,
                    "source_groups": self.db.execute(
                        "SELECT COUNT(*) FROM (SELECT DISTINCT "
                        "evidence_id,tool_run_id,source_file FROM refs WHERE group_id=?)",
                        (identifier,),
                    ).fetchone()[0],
                },
                redact=False,
            )
            for ev, tool, file, positions, low, high in self.db.execute(
                "SELECT evidence_id,tool_run_id,source_file,SUM(position>=0),"
                "MIN(CASE WHEN position>=0 THEN position END),"
                "MAX(CASE WHEN position>=0 THEN position END) "
                "FROM refs WHERE group_id=? GROUP BY evidence_id,tool_run_id,source_file "
                "ORDER BY evidence_id,tool_run_id,source_file",
                (identifier,),
            ):
                unknown = self.db.execute(
                    "SELECT COUNT(*) FROM unknown_refs WHERE group_id=? "
                    "AND evidence_id=? AND tool_run_id=? AND source_file=?",
                    (identifier, ev, tool, file),
                ).fetchone()[0]
                self.add(
                    "finding_sources",
                    {
                        "table": self.table_label(table),
                        "field": (
                            field
                            if kind == "record"
                            else self.alias(field, "FIELD")
                            if field
                            else ""
                        ),
                        "rule_id": rule,
                        "kind": kind,
                        "result": result,
                        "evidence_id": ev,
                        "tool_run_id": tool,
                        "source_file": self.alias(file, "SOURCE"),
                        "observed_locations": positions,
                        "first_position": low,
                        "last_position": high,
                        "unknown_locations": unknown,
                    },
                    redact=False,
                )
        self.metadata["counts"] = {
            section: count
            for section, count in self.db.execute(
                "SELECT section,COUNT(*) FROM entries GROUP BY section ORDER BY section"
            )
        }
        for table in (
            "aliases",
            "members",
            "occurrences",
            "refs",
            "unknown_refs",
            "record_tables",
            "groups",
            "seen_inputs",
            "totals",
            "counters",
        ):
            self.db.execute(f"DROP TABLE {table}")
        self.db.commit()

    def prepare_pdf_steps(self):
        from adapters.persistence.pdf_report import render_summary_steps

        yield from render_summary_steps(self)

    def prepare_pdf(self):
        for _ in self.prepare_pdf_steps():
            pass


def prepare_summary(connection, case_id, **options):
    steps = prepare_summary_steps(connection, case_id, **options)
    while True:
        try:
            next(steps)
        except StopIteration as completed:
            return completed.value


def prepare_summary_steps(
    connection, case_id, *, redacted=False, preferences=None, examiner_profile=None, now=None
):
    row = connection.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"case not found: {case_id}")
    p = SummaryProjection(
        case_id,
        redacted=redacted,
        moment=now() if now else datetime.now(UTC),
        settings={"preferences": preferences or {}, "examiner_profile": examiner_profile or {}},
    )
    try:
        p.add("case", _row(row))
        analysed_at = connection.execute(
            "SELECT MAX(saved_at) FROM analysis_results WHERE case_id=?", (case_id,)
        ).fetchone()[0]
        p.metadata["analysed_at"] = analysed_at
        normalization = connection.execute(
            "SELECT scope_json,counts_json,normalized_at FROM normalizations WHERE case_id=?",
            (case_id,),
        ).fetchone()
        if normalization:
            scope = json.loads(normalization["scope_json"])
            databases, tables = scope.get("databases", []), scope.get("tables", [])
            p.add(
                "scope",
                {
                    "recorded": True,
                    "all_evidence": not databases and not tables,
                    "databases": [p.alias(name, "DATABASE") for name in sorted(databases)],
                    "tables": [p.alias(".".join(table), "TABLE") for table in sorted(tables)],
                },
                redact=False,
            )
            for category, counts in sorted(json.loads(normalization["counts_json"]).items()):
                p.add(
                    "scope_counts",
                    {"category": category, "in_scope": counts[0], "stored": counts[1]},
                    redact=False,
                )
        else:
            p.add("scope", {"recorded": False, "all_evidence": False}, redact=False)
        for row in connection.execute(
            "SELECT * FROM evidence_files WHERE case_id=? ORDER BY evidence_id", (case_id,)
        ):
            p.add("evidence", _row(row))
        for row in connection.execute(
            "SELECT tool_name,tool_version,executable_sha256,status,COUNT(*) AS runs,"
            "MIN(started_at) AS first_run,MAX(finished_at) AS last_run,"
            "COUNT(DISTINCT arguments_json) AS commands,COUNT(stdout_sha256) AS hashed_outputs,"
            "COUNT(stderr_sha256) AS hashed_diagnostics FROM tool_runs WHERE case_id=? "
            "GROUP BY tool_name,tool_version,executable_sha256,status "
            "ORDER BY tool_name,tool_version,executable_sha256,status",
            (case_id,),
        ):
            p.add("processing", dict(row))
        for row in connection.execute(
            "SELECT i.* FROM integrity_results i JOIN evidence_files e "
            "ON e.evidence_id=i.evidence_id WHERE e.case_id=? "
            "ORDER BY i.evidence_id,i.integrity_id",
            (case_id,),
        ):
            item = dict(row)
            item.pop("raw_summary", None)
            item.pop("page_counts_json", None)
            p.add("integrity", item)
        queries = {
            "physical": "SELECT t.database_name||'.'||t.table_name,t.is_deleted,COUNT(*) "
            "FROM physical_records t JOIN evidence_files e ON e.evidence_id=t.evidence_id "
            "WHERE e.case_id=? GROUP BY t.database_name,t.table_name,t.is_deleted",
            "events": "SELECT t.database_name||'.'||t.table_name,t.event_type,COUNT(*) "
            "FROM binlog_events t JOIN evidence_files e ON e.evidence_id=t.evidence_id "
            "WHERE e.case_id=? GROUP BY t.database_name,t.table_name,t.event_type",
            "schemas": "SELECT t.database_name||'.'||t.table_name,'available schemas',COUNT(*) "
            "FROM schemas t JOIN evidence_files e ON e.evidence_id=t.evidence_id "
            "WHERE e.case_id=? GROUP BY t.database_name,t.table_name",
        }
        for section, sql in queries.items():
            yield {"stage": section, "processed": 0}
            for table, label, count in connection.execute(sql, (case_id,)):
                if section == "physical":
                    label = "Deleted rows" if label else "Live rows"
                p.count(section, table, str(label), count)

        stages = {
            "reconciliation": {"records": {"record", "fields", "rollup", "rollup_rule_id"}},
            "grouping": {"transactions": {"status"}, "ungrouped_events": {"reason"}},
            "correlation": {
                "records": {"record", "method"},
                "unsupported_tables": {"database", "table", "reason"},
                "uncertain_tables": None,
            },
            "reconstruction": {
                "histories": {"record", "method", "before_image_mismatch", "partial_image_columns"}
            },
        }
        for stage, fields in stages.items():
            include = set(fields) | {"findings", "coverage"}
            for processed, (member, index, value, _) in enumerate(
                analysis_members(connection, case_id, stage, include=include, item_fields=fields, checkpoints=True)
            ):
                if member is STREAM_PROGRESS:
                    yield {"stage": "reading_" + stage, **value}
                    continue
                if processed % 32 == 0:
                    yield {"stage": stage, "processed": processed}
                if index == -1:
                    continue
                if member == "findings":
                    p.finding(value)
                elif member == "coverage":
                    if not p.db.execute(
                        "INSERT OR IGNORE INTO seen_inputs VALUES (?,?)",
                        ("coverage", digest(value)),
                    ).rowcount:
                        continue
                    # Individual gap objects describe evidence limitations, not record values.
                    for gap in value.get("gaps", []):
                        p.add("coverage_gaps", gap)
                    inventory = value.get("inventory")
                    p.add(
                        "coverage",
                        {"check": "Index available", "value": inventory is not None},
                        redact=False,
                    )
                    p.add(
                        "coverage",
                        {
                            "check": "Complete log coverage",
                            "value": inventory is not None and not value.get("gaps"),
                        },
                        redact=False,
                    )
                    p.add(
                        "coverage",
                        {
                            "check": "Observed log files",
                            "value": len(value.get("observed_files", [])),
                        },
                        redact=False,
                    )
                elif member == "records" and stage == "reconciliation":
                    record = value["record"]
                    table = record.get("table", "Unknown")
                    record_id = record["id"]
                    p.db.execute(
                        "INSERT OR IGNORE INTO record_tables VALUES (?,?)", (record_id, table)
                    )
                    p.tally(table, "records", value["rollup"])
                    if value["rollup"] in EXCEPTIONS:
                        p.group(
                            kind="record",
                            table=table,
                            field="record classification",
                            result=value["rollup"],
                            rule_id=value.get("rollup_rule_id", "R-ROLL-000"),
                            record_id=record_id,
                            identity=digest((record_id, "rollup")),
                            context={
                                "rollup": value["rollup"],
                                "field_rules": sorted(
                                    {
                                        (field["result"], field["rule_id"])
                                        for field in value["fields"]
                                    }
                                ),
                            },
                            provenance=[field.get("provenance", {}) for field in value["fields"]],
                        )
                    for field in value["fields"]:
                        result = field["result"]
                        p.tally(table, "fields", result)
                        if result in EXCEPTIONS:
                            p.group(
                                kind="comparison",
                                table=table,
                                field=field["field"],
                                result=result,
                                rule_id=field["rule_id"],
                                record_id=record_id,
                                identity=digest(
                                    (record_id, field["field"], result, field["rule_id"])
                                ),
                                context={
                                    "findings": field.get("findings", []),
                                    "log": field.get("log"),
                                    "physical": field.get("phys"),
                                },
                                provenance=field.get("provenance", {}),
                            )
                elif member == "transactions":
                    p.count("transactions", "", value["status"])
                elif member == "ungrouped_events":
                    p.count("transactions", "", "Ungrouped events")
                elif member == "histories":
                    table = value["record"].get("table", "Unknown")
                    p.count("histories", table, "Record histories")
                    if value.get("before_image_mismatch"):
                        p.count("histories", table, "Before-image disagreements")
                    if value.get("partial_image_columns"):
                        p.count("histories", table, "Histories with partial images")
                elif member == "records":
                    p.count("correlation", value["record"].get("table", "Unknown"), value["method"])
                elif member == "unsupported_tables":
                    p.count(
                        "schemas", value["database"] + "." + value["table"], "Unsupported tables"
                    )
                elif member == "uncertain_tables":
                    p.count("schemas", ".".join(value), "Uncertain table coverage")

        for row in connection.execute(
            "SELECT * FROM warnings WHERE case_id=? ORDER BY code,evidence_id,warning_id",
            (case_id,),
        ):
            item = _row(row)
            context = item.get("context") or {}
            p.group(
                kind="warning",
                table=context.get("table") or "Case / unknown table",
                rule_id=item["code"],
                evidence_id=item.get("evidence_id") or "Unknown",
                identity=item["warning_id"],
                context=context,
                provenance=[
                    {
                        "evidence_id": item.get("evidence_id"),
                        "tool_run_id": item.get("tool_run_id"),
                        "source_file": context.get("source_file"),
                        "log_position": context.get("log_position"),
                        "row_index": context.get("row_index"),
                    }
                ],
            )
        for row in connection.execute(
            "SELECT * FROM binlog_inventory WHERE evidence_id IN "
            "(SELECT evidence_id FROM evidence_files WHERE case_id=?) ORDER BY evidence_id",
            (case_id,),
        ):
            item = _row(row)
            for key in ("listed_files", "present_files", "missing_files"):
                p.add(
                    "log_inventory",
                    {
                        "evidence_id": item["evidence_id"],
                        "category": key.replace("_", " "),
                        "count": len(item[key]),
                    },
                    redact=False,
                )
        yield {"stage": "finalizing summary", "processed": 0}
        for status in ("committed", "rolled_back", "incomplete", "Ungrouped events"):
            p.count("transactions", "", status, 0)
        p.finish()
        return p
    except BaseException:
        p.close()
        raise
