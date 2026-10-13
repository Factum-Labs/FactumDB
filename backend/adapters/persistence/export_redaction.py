"""Conservative offline sharing projection. Never changes the source database."""

import json
import re
import secrets

POLICY = {
    "mode": "redacted",
    "version": 3,
    "note": "Pseudonymized sharing copy, not an exact evidence export. Database identifiers "
    "and values and evidence filenames are replaced. Case names, examiner identity, tool "
    "metadata, provenance IDs, hashes, timestamps and acquisition methods are retained. "
    "Free-text notes, context, paths, commands and diagnostics are withheld. "
    "Counts and structural positions remain. "
    "This does not guarantee anonymity.",
}

_OMIT = {
    "examiner",
    "examiner_profile",
    "actor_id",
    "actor_username",
    "organization",
    "description",
    "notes",
    "examiner_notes",
    "acquisition_method",
    "source_path",
    "working_copy_path",
    "workspace_path",
    "executable_path",
    "stdout_path",
    "stderr_path",
    "arguments",
    "arguments_json",
    "raw_summary",
    "context",
    "message",
    "reason",
    "skip_reason",
    "error_message",
    "error_code",
}

# Only schema-defined fields at a recognized row boundary are disclosed.
# Nested database images are processed separately before these exceptions.
_COMMON_METADATA = {"case_id", "evidence_id", "tool_run_id", "actor_id", "actor_username"}
_SECTION_FIELDS = {
    "cases": {"case_name", "examiner", "created_at"},
    "evidence_files": {
        "source_sha256",
        "working_copy_sha256",
        "registered_at",
        "acquisition_method",
    },
    "tool_runs": {
        "tool_name",
        "tool_version",
        "executable_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "started_at",
        "finished_at",
    },
    "processing": {"tool_name", "tool_version", "executable_sha256", "first_run", "last_run"},
    "integrity_results": {"checked_at"},
    "analysis_metadata": {"saved_at"},
    "normalizations": {"normalized_at"},
    "pipeline_runs": {"started_at", "finished_at", "created_at"},
    "physical_extractions": {"extracted_at"},
    "warnings": {"created_at"},
    "schemas": set(),
    "schema_columns": set(),
    "schema_summaries": set(),
    "physical_records": set(),
    "binlog_events": set(),
    "transactions": set(),
    "transaction_events": set(),
    "binlog_inventory": set(),
    "case_scopes": set(),
    "table_creations": set(),
    "coverage_gaps": set(),
    "log_inventory": set(),
    "source": {"tool_name"},
    "examiner_profile": {"display_name", "organization", "examiner_id"},
}
_SECTION_NAMES = {"case": "cases", "evidence": "evidence_files", "integrity": "integrity_results"}


def examiner_metadata(profile):
    """Only the structured examiner fields, never arbitrary profile free text."""
    return {
        key: value for key, value in profile.items() if key in _SECTION_FIELDS["examiner_profile"]
    }


_VALUE_MAPS = {"values", "before", "after", "observed_values"}
_ENUM_KEYS = {
    "status",
    "verification_status",
    "integrity_status",
    "result",
    "rollup",
    "severity",
    "presence",
    "presence_before",
    "presence_after",
    "kind",
    "stage",
    "event_type",
    "tool_name",
    "transaction_status",
    "method",
}
_ENUM_VALUES = {
    "registered",
    "verified",
    "hash_mismatch",
    "valid",
    "damaged",
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
    "committed",
    "rolled_back",
    "incomplete",
    "Committed",
    "Rolled back",
    "Incomplete",
    "INSERT",
    "UPDATE",
    "DELETE",
    "ibd",
    "binlog",
    "binlog_index",
    "ibd2sdi",
    "ibd2sql",
    "mysqlbinlog",
    "innochecksum",
    "grouping",
    "correlation",
    "reconstruction",
    "reconciliation",
    "present",
    "absent",
    "unknown",
    "Exact",
    "Strong",
    "Conflicting",
    "Unresolved",
    "Unsupported",
    "Partial",
}


def alias_category(key):
    """Semantic categories shared by summary fields and assembled references."""
    categories = {
        "case_id": "CASE",
        "case_name": "CASE-NAME",
        "table": "TABLE",
        "table_name": "TABLE",
        "tables": "TABLE",
        "database": "DATABASE",
        "database_name": "DATABASE",
        "databases": "DATABASE",
        "field": "FIELD",
        "column": "FIELD",
        "evidence_id": "EVIDENCE",
        "tool_run_id": "RUN",
        "filename": "SOURCE",
        "source_file": "SOURCE",
        "after_file": "SOURCE",
        "before_file": "SOURCE",
        "tool_version": "VERSION",
    }
    if key.endswith("sha256"):
        return "HASH"
    if key.endswith("_at") or key in {"first_run", "last_run", "analysed_at"}:
        return "TIME"
    return categories.get(key, "VALUE")


def make_redactor(aliases=None, *, prefix=None, compact=False, typed=False):
    """Fresh aliases per export; the mapping exists only for this invocation.

    Text outside approved metadata is aliased rather than scanned for secrets.
    Evidence scalars (including numbers) are aliased too. Equality survives;
    original types and values do not. SQL NULL and unobserved markers survive.
    """
    if aliases is None:
        aliases = {}
    prefix = prefix if prefix is not None else secrets.token_hex(4)
    category_counts = {}

    def alias(value, category="VALUE", *, missing=True):
        if typed and missing and (value is None or value in ("", "Unknown", "[REDACTED]")):
            return value
        # Rendered comparison values and stored scalars share an alias.
        if isinstance(value, dict):
            for tag in ("__decimal__", "__datetime__"):
                if tag in value:
                    value = value[tag]
                    break
        identity = (
            str(value)
            if isinstance(value, (str, int, float))
            else json.dumps(value, sort_keys=True, ensure_ascii=False)
        )
        if typed:
            identity = json.dumps([category, identity], ensure_ascii=False)
        if identity not in aliases:
            if typed:
                ordinal = category_counts.get(category, 0) + 1
                category_counts[category] = ordinal
                aliases[identity] = f"[{category}-{ordinal:03d}]"
            else:
                ordinal = len(aliases) + 1
                aliases[identity] = (
                    f"[S-{ordinal:04d}]" if compact else f"[VALUE-{prefix}-{ordinal:04d}]"
                )
        return aliases[identity]

    def visit(value, key="", evidence=False, *, section="", root=True):
        if value is None:
            return None
        if evidence:
            if isinstance(value, list):
                return [visit(item, evidence=True) for item in value]
            if isinstance(value, dict) and value.get("__unobserved__") is True:
                return {"__unobserved__": True}
            if isinstance(value, dict) and "__undecodable__" in value:
                return {"__undecodable__": "[REDACTED]"}
            return alias(value, missing=False)
        if isinstance(value, dict):
            section = _SECTION_NAMES.get(section, section)
            if {"evidence_id", "tool_run_id", "source_file"} <= value.keys() and (
                key in {"provenance", "derived_from"}
                or section.startswith("analysis_")
                or section == "analysis_results"
            ):
                section, root = "source", True
            allowed = (
                _COMMON_METADATA | _SECTION_FIELDS[section]
                if root and section in _SECTION_FIELDS
                else set()
            )
            result = {}
            for child_key, child in value.items():
                if child_key in _VALUE_MAPS and isinstance(child, dict):
                    result[child_key] = {
                        alias(k, "FIELD" if typed else "VALUE"): visit(v, evidence=True)
                        for k, v in child.items()
                    }
                elif child_key in {"key_values", "primary_key_values"}:
                    result[child_key] = visit(child, evidence=True)
                elif (
                    child_key in allowed
                    and (child is None or isinstance(child, (str, int, float, bool)))
                ) or (
                    child_key in {"filename", "source_file", "after_file", "before_file"}
                    and (child is None or child in ("", "Unknown"))
                ):
                    result[child_key] = child
                elif child_key in _OMIT or child_key.endswith("_path"):
                    result[child_key] = "[REDACTED]"
                elif child_key == "derived_from" and isinstance(child, dict):
                    result[child_key] = {
                        alias(k): visit(v, "derived_from", section=section, root=False)
                        for k, v in child.items()
                    }
                elif child_key in {"log", "phys", "log_value", "phys_value"} or (
                    child_key in {"before", "after"} and not isinstance(child, dict)
                ):
                    result[child_key] = visit(child, evidence=True)
                else:
                    result[child_key] = visit(child, child_key, section=section, root=False)
            return result
        if isinstance(value, list):
            return [visit(item, key, section=section, root=root) for item in value]
        if isinstance(value, str):
            if key in _ENUM_KEYS and value in _ENUM_VALUES:
                return value
            if key.endswith("rule_id") and re.fullmatch(r"R-[A-Z]+-\d{3}", value):
                return value
            return alias(value, alias_category(key) if typed else "VALUE")
        return value

    return visit, alias


def redact_document(document: dict) -> dict:
    """Redact one legacy in-memory document with consistent fresh aliases."""
    visit, _alias = make_redactor()
    # Keep the export envelope readable; only case content is transformed.
    result = {
        **document,
        "case_id": document["case_id"],
        "tables": {name: visit(rows, section=name) for name, rows in document["tables"].items()},
        "redaction": dict(POLICY),
    }
    return result
