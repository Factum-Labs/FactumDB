"""Section selection shared by preview and all report formats."""

from copy import deepcopy

SECTIONS = (
    ("case_details", "Case details"),
    ("evidence", "Evidence inventory"),
    ("hashes", "SHA-256 hashes"),
    ("tools", "Utility versions and commands"),
    ("integrity", "Page-integrity results"),
    ("schemas", "Schema mappings"),
    ("timeline", "Transaction timeline"),
    ("histories", "Record histories"),
    ("reconciliation", "Reconciliation results"),
    ("gaps", "Evidence gaps and limitations"),
    ("provenance", "Provenance references"),
    ("notes", "Examiner notes"),
)
BASE_SECTIONS = SECTIONS
OPTIONAL_SECTIONS = (
    ("exact_matches", "Exact comparison details"),
    ("physical_records", "All extracted physical records"),
    ("binlog_events", "All decoded binlog events"),
    ("complete_timeline", "Complete transaction timeline"),
    ("complete_histories", "Complete record histories"),
    ("complete_schemas", "Complete schema mappings"),
    ("intermediate_analysis", "Complete intermediate analysis"),
)
SECTIONS = BASE_SECTIONS + OPTIONAL_SECTIONS
DEPENDENCIES = {
    "hashes": ("evidence", "tools"),
    "reconciliation": ("schemas", "gaps"),
    "histories": ("schemas", "gaps"),
    "timeline": ("gaps",),
    "exact_matches": ("reconciliation",),
    "physical_records": ("histories", "schemas"),
    "binlog_events": ("timeline", "schemas"),
    "complete_timeline": ("timeline", "binlog_events"),
    "complete_histories": ("histories", "timeline", "schemas"),
    "complete_schemas": ("schemas",),
    "intermediate_analysis": ("histories", "timeline", "schemas", "binlog_events"),
}
TRACEABLE_SECTIONS = {
    "integrity", "schemas", "timeline", "histories", "reconciliation", "gaps",
    *(key for key, _ in OPTIONAL_SECTIONS),
}


def section_catalog():
    return [{"id": key, "title": title, "optional": (key, title) in OPTIONAL_SECTIONS,
             "dependencies": list(DEPENDENCIES.get(key, ())),
             "default_profiles": ["full"] if (key, title) in OPTIONAL_SECTIONS
             else ["investigator", "full"]} for key, title in SECTIONS]


def resolve_sections(profile, sections):
    if not isinstance(profile, str) or profile not in {"investigator", "full"}:
        raise ValueError("Supported export profiles are investigator and full")
    defaults = SECTIONS if profile == "full" else BASE_SECTIONS
    requested = validate_sections(sections) if sections is not None else [k for k, _ in defaults]
    effective = set(requested)
    while True:
        previous = set(effective)
        for key in list(effective):
            effective.update(DEPENDENCIES.get(key, ()))
        if effective & TRACEABLE_SECTIONS:
            effective.update({"evidence", "hashes", "tools", "provenance"})
        if previous == effective:
            break
    ordered = [key for key, _ in SECTIONS if key in effective]
    return {"requested_sections": requested, "sections": ordered,
            "automatic_sections": [key for key in ordered if key not in requested],
            "partial": any(key not in requested for key, _ in defaults)}
TABLE_SECTIONS = {
    "case_details": ("cases",),
    "evidence": ("evidence_files", "binlog_inventory"),
    "tools": ("tool_runs",),
    "integrity": ("integrity_results",),
    "schemas": ("schemas", "schema_columns", "table_creations"),
    "timeline": ("transactions", "transaction_events", "binlog_events"),
    "histories": ("physical_records", "physical_extractions"),
    "gaps": ("warnings", "case_scopes", "normalizations", "findings"),
    "provenance": ("pipeline_runs", "provenance"),
    "hashes": ("hashes",),
    "notes": ("cases",),
}
STAGE_SECTIONS = {
    "grouping": "timeline",
    "correlation": "histories",
    "reconstruction": "histories",
    "reconciliation": "reconciliation",
}
PROVENANCE_FIELDS = {
    "evidence_id",
    "tool_run_id",
    "provenance",
    "ref",
    "derived_from",
    "source_file",
    "log_position",
    "row_index",
    "page_no",
    "page_offset",
}


def validate_sections(value):
    if value is None:
        return None
    allowed = {key for key, _ in SECTIONS}
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(key, str) or key not in allowed for key in value)
        or len(value) != len(set(value))
    ):
        raise ValueError("Select one or more supported report sections")
    return [key for key, _ in SECTIONS if key in value]


def select_sections(document, sections):
    if sections is None:
        return document
    result = deepcopy(document)
    source = result["tables"]
    wanted = {table for section in sections for table in TABLE_SECTIONS.get(section, ())}
    tables = {key: value for key, value in source.items() if key in wanted}
    analyses = [
        row
        for row in source.get("analysis_results", [])
        if STAGE_SECTIONS.get(row["stage"]) in sections
    ]
    if analyses:
        tables["analysis_results"] = analyses
    if "gaps" in sections:
        tables["findings"] = [
            {
                "stage": row["stage"],
                "findings": row["result"].get("findings", []),
                "coverage": row["result"].get("coverage"),
            }
            for row in source.get("analysis_results", [])
        ]
    if "hashes" in sections:
        tables["hashes"] = [
            {
                "table": table,
                "row": index,
                **{key: value for key, value in row.items() if key.endswith("sha256")},
            }
            for table, records in source.items()
            for index, row in enumerate(records)
            if any(key.endswith("sha256") for key in row)
        ]
    if "provenance" in sections:
        tables["provenance"] = [
            {
                "table": table,
                "row": index,
                **{key: value for key, value in row.items() if key in PROVENANCE_FIELDS},
            }
            for table, records in source.items()
            for index, row in enumerate(records)
            if any(key in PROVENANCE_FIELDS for key in row)
        ]

    def filter_fields(value):
        if isinstance(value, list):
            return [filter_fields(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: (
                child
                if key in {"values", "before", "after", "observed_values"}
                else filter_fields(child)
            )
            for key, child in value.items()
            if not (key.endswith("sha256") and "hashes" not in sections)
            and not (key in PROVENANCE_FIELDS and "provenance" not in sections)
            and not (key in {"findings", "coverage", "context"} and "gaps" not in sections)
        }

    tables = filter_fields(tables)
    if "cases" in tables:
        for row in tables["cases"]:
            if "notes" not in sections:
                row.pop("examiner_notes", None)
            if "case_details" not in sections:
                for key in list(row):
                    if key not in {"case_id", "examiner_notes"}:
                        del row[key]
    result["tables"] = tables
    result["selection"] = {"sections": sections, "partial": len(sections) != len(BASE_SECTIONS)}
    return result


def report_sections(document):
    chosen = document.get("selection", {}).get("sections", [key for key, _ in BASE_SECTIONS])
    sections = []
    for index, (key, title) in enumerate(SECTIONS, 1):
        if key not in chosen:
            continue
        rows = []
        for table in TABLE_SECTIONS.get(key, ()):
            for row in document["tables"].get(table, []):
                if table == "cases":
                    row = (
                        {"examiner_notes": row.get("examiner_notes")}
                        if key == "notes"
                        else {k: v for k, v in row.items() if k != "examiner_notes"}
                    )
                rows.append({"table": table, "data": row})
        rows.extend(
            {"table": "analysis_results", "data": row}
            for row in document["tables"].get("analysis_results", [])
            if STAGE_SECTIONS.get(row["stage"]) == key
        )
        if key == "case_details" and "presentation" in document:
            rows.append({"table": "presentation", "data": document["presentation"]})
        sections.append(
            {
                "id": key,
                "number": index,
                "title": title,
                "rows": rows,
                "note": (
                    "FactumDB does not attribute changes to a person or determine intent."
                    if key == "gaps"
                    else ""
                ),
            }
        )
    return sections
