"""Complete JSON evidence exports, with legacy version-2 compatibility."""

import json
from datetime import datetime, timezone
from pathlib import Path

from adapters.persistence._timestamps import to_text
from adapters.persistence._reconciliation import expand_reconciliation
from adapters.persistence.export_redaction import redact_document
from adapters.persistence.export_sections import select_sections, validate_sections
from adapters.persistence.sqlite_report_repository import SqliteReportRepository
from core.application.errors import NotFoundError
from core.engine import ENGINE_REVISION, ANALYSIS_FORMAT_VERSION
from core.application.preferences import report_times, time_label

FORMAT = "factumdb-case-export"
FORMAT_VERSION = 2

VALUE_TAGS = {
    "__decimal__": "an exact DECIMAL value, written as text so no digit is lost",
    "__datetime__": "a date and time in ISO-8601",
    "__undecodable__": "a value the tool could not decode; the text says why",
    "__unobserved__": "a column the row image did not include",
}

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
    for result in tables["analysis_results"]:
        if result["stage"] == "reconciliation":
            result["result"] = expand_reconciliation(result["result"])
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


def prepare_export(connection, case_id, *, now=_utc_now, preferences=None,
                   examiner_profile=None, redacted=False, sections=None, profile=None):
    if sections is not None or profile not in {None, "full"}:
        raise ValueError("JSON exports contain the complete case; profile and sections cannot reduce it")
    if profile is not None:
        from adapters.persistence.investigator_export import prepare_projection
        return prepare_projection(connection, case_id, now=now, preferences=preferences,
                                  examiner_profile=examiner_profile, redacted=redacted,
                                  sections=sections, profile=profile)
    document = select_sections(case_export(connection, case_id, now=now),
                               validate_sections(sections))
    if redacted:
        document = redact_document(document)
        examiner_profile = {}
    if preferences is not None:
        document["presentation"] = {
            "timezone": time_label(preferences),
            "examiner_profile": (examiner_profile or {}) if sections is None or "case_details" in sections else {},
            "display_times": report_times(document["tables"], preferences),
            "note": ("Timestamps are aliased in this sharing copy." if redacted
                     else "Original timestamps remain unchanged in tables."),
        }
    return document


def write_json(
    connection, case_id: str, path, *, now=_utc_now, preferences=None,
    examiner_profile=None, redacted=False, sections=None, prepared_document=None,
    actor_id=None, actor_username=None,
    profile=None,
) -> Path:
    """The whole case in one new file, recorded as the next JSON version."""
    if sections is not None or profile not in {None, "full"}:
        raise ValueError("JSON exports contain the complete case; profile and sections cannot reduce it")
    moment = now()
    document = prepared_document if prepared_document is not None else prepare_export(
        connection, case_id, now=lambda: moment, preferences=preferences,
        examiner_profile=examiner_profile, redacted=redacted, sections=sections, profile=profile,
    )
    path = Path(path)
    from adapters.persistence.investigator_export import ExportProjection
    if (isinstance(document, ExportProjection) and
            (document.profile != "full" or document.selection["partial"])) or (
            isinstance(document, dict) and document.get("selection", {}).get("partial")):
        if isinstance(document, ExportProjection) and prepared_document is None:
            document.close()
        raise ValueError("Cannot export a partial JSON projection")
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as out:
            if isinstance(document, ExportProjection):
                document.write_json(out)
            else:
                json.dump(document, out, indent=2, sort_keys=True, ensure_ascii=False)
                out.write("\n")
        _record(connection, case_id, "json", path, [path], moment,
                actor_id=actor_id, actor_username=actor_username)
    finally:
        if isinstance(document, ExportProjection) and prepared_document is None:
            document.close()
    return path


def _record(connection, case_id, format, location, files, moment, **actor):
    """Add a finished export to the case's report history."""
    SqliteReportRepository(connection, now=lambda: moment).record(
        case_id, format, location, files, **actor,
    )


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
