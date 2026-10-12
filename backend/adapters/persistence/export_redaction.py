"""Conservative offline sharing projection. Never changes the source database."""

import json
import re
import secrets

POLICY = {
    "mode": "redacted",
    "version": 1,
    "note": "Pseudonymized sharing copy, not an exact evidence export. All evidence values "
    "and text identifiers are replaced. Free-text context, personal metadata, paths, "
    "commands and diagnostic text are omitted. Counts and structural positions remain. "
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
    "acquisition_method",
    "source_path",
    "working_copy_path",
    "workspace_path",
    "executable_path",
    "stdout_path",
    "stderr_path",
    "arguments",
    "context",
    "message",
    "reason",
    "skip_reason",
    "error_message",
    "error_code",
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


def make_redactor(aliases=None, *, prefix=None, compact=False):
    """Fresh aliases per export; the mapping exists only for this invocation.

    All text is aliased rather than scanned with fallible secret/PII regexes.
    Evidence scalars (including numbers) are aliased too. Equality survives;
    original types and values do not. SQL NULL and unobserved markers survive.
    """
    if aliases is None:
        aliases = {}
    prefix = prefix if prefix is not None else secrets.token_hex(4)

    def alias(value):
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
        if identity not in aliases:
            ordinal = len(aliases) + 1
            aliases[identity] = (
                f"[S-{ordinal:04d}]" if compact else f"[VALUE-{prefix}-{ordinal:04d}]"
            )
        return aliases[identity]

    def visit(value, key="", evidence=False):
        if value is None:
            return None
        if evidence:
            if isinstance(value, list):
                return [visit(item, evidence=True) for item in value]
            if isinstance(value, dict) and value.get("__unobserved__") is True:
                return {"__unobserved__": True}
            if isinstance(value, dict) and "__undecodable__" in value:
                return {"__undecodable__": "[REDACTED]"}
            return alias(value)
        if isinstance(value, dict):
            result = {}
            for child_key, child in value.items():
                if child_key in _OMIT or child_key.endswith("_path"):
                    result[child_key] = "[REDACTED]"
                elif child_key in _VALUE_MAPS and isinstance(child, dict):
                    result[child_key] = {
                        alias(k): visit(v, evidence=True) for k, v in child.items()
                    }
                elif child_key == "derived_from" and isinstance(child, dict):
                    result[child_key] = {alias(k): visit(v) for k, v in child.items()}
                elif (
                    child_key in {"before", "after", "log", "phys", "log_value", "phys_value"}
                    and not isinstance(child, (list, dict))
                ) or (
                    child_key in {"log", "phys"}
                    and isinstance(child, dict)
                    and any(k.startswith("__") for k in child)
                ):
                    result[child_key] = visit(child, evidence=True)
                else:
                    result[child_key] = visit(child, child_key)
            return result
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if isinstance(value, str):
            if key in _ENUM_KEYS and value in _ENUM_VALUES:
                return value
            if key.endswith("rule_id") and re.fullmatch(r"R-[A-Z]+-\d{3}", value):
                return value
            return alias(value)
        return value

    return visit, alias


def redact_document(document: dict) -> dict:
    """Redact one legacy in-memory document with consistent fresh aliases."""
    visit, alias = make_redactor()
    # Keep the export envelope readable; only case content is transformed.
    result = {
        **document,
        "case_id": alias(document["case_id"]),
        "tables": visit(document["tables"]),
        "redaction": dict(POLICY),
    }
    return result
