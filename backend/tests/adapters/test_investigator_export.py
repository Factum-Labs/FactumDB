import io
import json
import sqlite3

# Imported pytest fixtures are consumed through test parameter names.
# ruff: noqa: F811
import pytest

from adapters.persistence.case_export import case_export, write_json
from adapters.persistence.export_sections import OPTIONAL_SECTIONS, resolve_sections
from adapters.persistence.investigator_export import (
    DiskAliases,
    JsonMembers,
    analysis_members,
    expand_document,
    prepare_projection,
)
from tests.adapters.test_case_export import connection_of, stores  # noqa: F401
from tests.adapters.test_finding_provenance import analysed  # noqa: F401
from tests.adapters.test_sqlite_normalization import case  # noqa: F401


def test_streamed_compact_reconciliation_matches_legacy_with_summary_selection(case, analysed):
    from adapters.persistence._reconciliation import expand_reconciliation

    connection = connection_of(case)
    stored = json.loads(connection.execute(
        "SELECT result_json FROM analysis_results WHERE case_id=? AND stage=?",
        ("case-1", "reconciliation"),
    ).fetchone()[0])
    assert stored["storage_format"] == "factumdb-reconciliation"
    for include, item_fields in (
        (None, None),
        ({"records", "findings", "coverage"},
         {"records": {"record", "fields", "rollup", "rollup_rule_id"}}),
    ):
        compact = list(analysis_members(
            connection, "case-1", "reconciliation", include, item_fields
        ))
        stream = io.BytesIO(json.dumps(expand_reconciliation(stored)).encode())
        legacy = list(JsonMembers(stream).members(include, item_fields))
        assert [item[:3] for item in compact] == legacy


@pytest.mark.parametrize("damage", [
    "version", "field_reference", "finding_reference", "missing_pool",
])
def test_streamed_compact_reconciliation_rejects_invalid_storage(case, analysed, damage):
    connection = connection_of(case)
    stored = json.loads(connection.execute(
        "SELECT result_json FROM analysis_results WHERE case_id=? AND stage=?",
        ("case-1", "reconciliation"),
    ).fetchone()[0])
    if damage == "version":
        stored["storage_version"] = 999
    elif damage == "field_reference":
        stored["records"][0]["field_refs"] = [True]
    elif damage == "finding_reference":
        stored["finding_refs"] = [len(stored["finding_pool"])]
    else:
        del stored["finding_pool"]
    connection.execute(
        "UPDATE analysis_results SET result_json=? WHERE case_id=? AND stage=?",
        (json.dumps(stored), "case-1", "reconciliation"),
    )
    with pytest.raises(ValueError):
        list(analysis_members(connection, "case-1", "reconciliation"))


def test_disk_alias_count_never_rescans_existing_aliases():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE aliases(original TEXT PRIMARY KEY, alias TEXT)")
    aliases = DiskAliases(db)
    queries = []
    db.set_trace_callback(queries.append)
    for index in range(500):
        aliases[str(index)] = f"alias-{len(aliases)}"
    assert len(aliases) == 500
    aliases["0"] = "replacement"
    assert len(aliases) == 500
    del aliases["0"]
    assert len(aliases) == 499
    with pytest.raises(KeyError):
        del aliases["missing"]
    assert not any("COUNT(" in query.upper() for query in queries)
    db.close()


def document(projection):
    output = io.StringIO()
    projection.write_json(output)
    return json.loads(output.getvalue())


def without_display(value, key=""):
    if key in {"values", "before", "after", "observed_values", "context", "arguments"}:
        return value
    if isinstance(value, list):
        return [without_display(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        k: without_display(v, k)
        for k, v in value.items()
        if k not in {"log_display", "phys_display", "rollup_label"}
        and not ("key_columns" in value and k == "label")
    }


def test_full_round_trip_preserves_evidence_and_all_analysis(case, analysed):
    connection = connection_of(case)
    original = case_export(connection, "case-1")
    projection = prepare_projection(connection, "case-1", profile="full")
    try:
        compact = document(projection)
        expanded = expand_document(compact)
        expected = without_display(original["tables"])
        actual = expanded["tables"]
        expected_stages = {row["stage"]: row for row in expected.pop("analysis_results")}
        actual_stages = {row["stage"]: row for row in actual.pop("analysis_results")}
        assert actual == expected
        assert actual_stages == expected_stages
        assert not compact["selection"]["partial"]
        assert len({obj["id"] for obj in compact["objects"]}) == len(compact["objects"])
        assert any(obj["occurrences"] > 1 for obj in compact["objects"])
        assert any(obj["kind"] == "event" and obj["occurrences"] > 1 for obj in compact["objects"])
    finally:
        projection.close()


def test_investigator_keeps_all_non_exact_and_totals(case, analysed):
    connection = connection_of(case)
    original = case_export(connection, "case-1")
    source = next(
        row["result"]
        for row in original["tables"]["analysis_results"]
        if row["stage"] == "reconciliation"
    )
    projection = prepare_projection(connection, "case-1")
    try:
        exported = document(projection)
        expanded = expand_document(exported)
        recon = next(
            row["result"]
            for row in expanded["tables"]["analysis_results"]
            if row["stage"] == "reconciliation"
        )
        fields = [field for record in recon.get("records", []) for field in record["fields"]]
        expected = [
            without_display(field) for field in source["rows"] if field["result"] != "Exact"
        ]
        assert fields == expected
        assert sum(
            row["count"]
            for row in exported["tables"]["reconciliation_totals"]
            if row["granularity"] == "fields"
        ) == len(source["rows"])
        assert "exact_matches" not in exported["selection"]["sections"]
        assert (
            projection.json_size
            == len(json.dumps(exported, ensure_ascii=False, separators=(",", ":")).encode()) + 1
        )
    finally:
        projection.close()


@pytest.mark.parametrize("section", [key for key, _ in OPTIONAL_SECTIONS])
def test_optional_sections_have_resolved_dependencies(case, analysed, section):
    projection = prepare_projection(connection_of(case), "case-1", sections=[section])
    try:
        exported = document(projection)
        assert section in exported["selection"]["sections"]
        assert {"evidence", "tools", "hashes", "provenance"} <= set(
            exported["selection"]["sections"]
        )
        assert exported["selection"]["automatic_sections"]
        assert exported["selection"]["partial"]
        expand_document(exported)  # Every reference resolves, even for additions alone.
    finally:
        projection.close()


def test_redaction_is_consistent_and_business_column_names_are_atomic(stores):
    projection = prepare_projection(connection_of(stores), "case-1", profile="full", redacted=True)
    try:
        exported = document(projection)
        text = json.dumps(exported)
        for secret in ("HYPERLINK", "/seized/", "payments", "4000.10"):
            assert secret not in text
        expanded = expand_document(exported)
        assert expanded["tables"]["physical_records"]
        assert "Unsuitable for independent reanalysis" in exported["redaction"]["note"]
    finally:
        projection.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_sharing_exports_preserve_metadata_and_provenance(stores, streaming):
    from adapters.persistence.case_export import prepare_export

    connection = connection_of(stores)
    connection.execute(
        "UPDATE cases SET examiner='Examiner Alice', "
        "examiner_notes='private note', case_name='private case' WHERE case_id='case-1'"
    )
    connection.execute(
        "UPDATE tool_runs SET tool_version='custom-version-9', "
        "executable_sha256='executable-original' WHERE case_id='case-1'"
    )
    connection.execute(
        "UPDATE evidence_files SET acquisition_method='Forensic image', "
        "actor_username='Recorded Actor' WHERE case_id='case-1'"
    )
    connection.execute(
        "UPDATE physical_records SET values_json=json_set(values_json, "
        "'$.examiner', 'database-person', '$.tool_version', 'database-version', "
        "'$.created_at', 'database-time', '$.source_sha256', 'database-hash', "
        "'$.case_name', 'database-case-name')"
    )
    before = case_export(connection, "case-1")["tables"]
    profile = {
        "display_name": "Profile Alice",
        "organization": "Forensic Lab",
        "examiner_id": "EX-12",
        "notes": "private profile note",
    }
    projection = None
    if streaming:
        projection = prepare_projection(
            connection, "case-1", profile="full", redacted=True, examiner_profile=profile
        )
        exported = document(projection)
        tables = expand_document(exported)["tables"]
    else:
        exported = prepare_export(
            connection,
            "case-1",
            redacted=True,
            preferences={"time_mode": "utc", "utc_offset_minutes": 0},
            examiner_profile=profile,
        )
        tables = exported["tables"]
    try:
        assert exported["case_id"] == "case-1"
        assert exported["redaction"]["version"] == 3
        assert tables["cases"][0]["case_name"] == "private case"
        assert exported["presentation"]["examiner_profile"] == {
            key: profile[key] for key in ("display_name", "organization", "examiner_id")
        }
        assert tables["cases"][0]["examiner"] == "Examiner Alice"
        assert tables["cases"][0]["created_at"] == before["cases"][0]["created_at"]
        evidence = {row["evidence_id"]: row for row in tables["evidence_files"]}
        tools = {row["tool_run_id"]: row for row in tables["tool_runs"]}
        for original in before["evidence_files"]:
            row = evidence[original["evidence_id"]]
            for key in (
                "case_id",
                "source_sha256",
                "working_copy_sha256",
                "registered_at",
                "actor_username",
                "acquisition_method",
            ):
                assert row[key] == original[key]
            assert row["filename"] != original["filename"]
        for original in before["tool_runs"]:
            row = tools[original["tool_run_id"]]
            for key in (
                "case_id",
                "evidence_id",
                "tool_name",
                "tool_version",
                "executable_sha256",
                "stdout_sha256",
                "stderr_sha256",
                "started_at",
                "finished_at",
            ):
                assert row[key] == original[key]
        for row in tables["physical_records"]:
            assert row["evidence_id"] in evidence
            assert row["tool_run_id"] in tools
        for row in tables["binlog_events"]:
            assert row["source_file"] == evidence[row["evidence_id"]]["filename"]
        if streaming:
            for obj in exported["objects"]:
                if obj["kind"] == "source":
                    source = obj["value"]
                    assert source["evidence_id"] in evidence
                    assert source["tool_run_id"] in tools
                    assert source["source_file"] == evidence[source["evidence_id"]]["filename"]
        text = json.dumps(exported)
        for secret in (
            "private note",
            "private profile note",
            "payments",
            "HYPERLINK",
            "4000.10",
            "/seized/",
            "database-person", "database-version", "database-time", "database-hash",
            "database-case-name",
        ):
            assert secret not in text
        assert case_export(connection, "case-1")["tables"] == before
    finally:
        if projection:
            projection.close()


def test_incremental_json_handles_unicode_numbers_and_empty_arrays():
    class SmallReads(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 3))

    value = {
        "items": [123456789, {"text": "සිංහල", "values": {"label": "unchanged"}}, None],
        "empty": [],
        "scalar": True,
    }
    rows = list(JsonMembers(SmallReads(json.dumps(value, ensure_ascii=False).encode())).members())
    assert rows == [
        ("items", 0, value["items"][0]),
        ("items", 1, value["items"][1]),
        ("items", 2, None),
        ("empty", -1, None),
        ("scalar", None, True),
    ]


def test_standalone_legacy_defaults_and_explicit_profile(stores, tmp_path):
    connection = connection_of(stores)
    legacy = write_json(connection, "case-1", tmp_path / "legacy.json")
    modern = write_json(connection, "case-1", tmp_path / "modern.json", profile="full")
    assert json.loads(legacy.read_text())["format_version"] == 2
    assert json.loads(modern.read_text())["format_version"] == 3



def test_section_defaults_and_dependency_protection():
    compact = resolve_sections("investigator", None)
    assert not compact["partial"]
    assert "binlog_events" not in compact["sections"]
    full = resolve_sections("full", None)
    assert "binlog_events" in full["sections"]
    assert not full["partial"]
    with pytest.raises(ValueError):
        resolve_sections("unsupported", None)


def test_all_classifications_tags_warnings_and_business_names_survive(stores):
    connection = connection_of(stores)
    records = []
    classifications = ["Exact", "Strong", "Partial", "Conflicting", "Unresolved", "Unsupported"]
    source = {
        "evidence_id": "ev-ibd",
        "tool_name": "ibd2sql",
        "tool_run_id": "sql",
        "source_file": "payments.ibd",
        "log_position": None,
        "row_index": None,
    }
    warning = {
        "rule_id": "R-PROV-001",
        "severity": "warning",
        "subject": {"kind": "case", "id": "case-1"},
        "context": {"message": "Location unknown"},
        "provenance": [source],
    }
    for index, classification in enumerate(classifications):
        identifier = f"payments:{index}"
        field = {
            "record_id": identifier,
            "field": "label",
            "result": classification,
            "log": {"__unobserved__": True},
            "phys": None,
            "rule_id": "R-RECON-001",
            "comparable": False,
            "provenance": {"log": [], "physical": source, "transaction_id": None},
            "findings": [],
        }
        if classification == "Unsupported":
            field["phys"] = {"__undecodable__": "Unsupported binary data"}
        records.append(
            {
                "record": {
                    "id": identifier,
                    "database": "shop",
                    "table": "shop.payments",
                    "key_columns": ["payment_id"],
                    "key_values": [str(index)],
                    "key": str(index),
                    "pk": str(index),
                    "label": str(index),
                },
                "fields": [field],
                "rollup": classification,
                "rollup_rule_id": "R-ROLL-001",
                "rollup_label": classification,
                "triggers": [],
                "findings": [],
            }
        )
    result = {
        "records": records,
        "rows": [record["fields"][0] for record in records],
        "coverage": {
            "observed_files": [],
            "gaps": [{"reason": "no_index", "rule_id": "R-COV-001", "missing_files": []}],
            "inventory": None,
            "findings": [warning],
        },
        "findings": [warning],
    }
    connection.execute(
        "INSERT INTO analysis_results VALUES (?,?,?,?)",
        ("case-1", "reconciliation", json.dumps(result), "2026-10-11T00:00:00Z"),
    )
    business = {
        "label": "literal label",
        "rollup_label": "literal rollup",
        "$ref": "literal reference",
        "context": "literal context",
        "source_sha256": "literal hash",
        "payment_id": 1,
    }
    connection.execute(
        "UPDATE physical_records SET values_json=? WHERE evidence_id='ev-ibd'",
        (json.dumps(business),),
    )
    projection = prepare_projection(
        connection, "case-1", sections=["reconciliation", "physical_records"]
    )
    try:
        exported = document(projection)
        expanded = expand_document(exported)
        comparisons = [obj["value"] for obj in exported["objects"] if obj["kind"] == "comparison"]
        assert {field["result"] for field in comparisons} == set(classifications) - {"Exact"}
        assert all(field["log"] == {"__unobserved__": True} for field in comparisons)
        assert next(field for field in comparisons if field["result"] == "Unsupported")["phys"] == {
            "__undecodable__": "Unsupported binary data"
        }
        assert {row["result"] for row in exported["tables"]["reconciliation_totals"]} == set(
            classifications
        )
        assert expanded["tables"]["physical_records"][0]["values"] == business
        findings = [obj for obj in exported["objects"] if obj["kind"] == "finding"]
        assert len(findings) == 1
        assert findings[0]["value"]["context"] == warning["context"]
        assert findings[0]["occurrences"] >= 2
    finally:
        projection.close()


def test_multiple_rows_at_one_log_position_keep_distinct_source_identity(stores):
    connection = connection_of(stores)
    connection.execute("""INSERT INTO binlog_events (
        event_id,evidence_id,tool_run_id,event_type,database_name,table_name,before_json,
        after_json,event_time_utc,raw_timestamp,gtid,source_file,log_position,row_index,thread_id)
        SELECT event_id || '-second-row', evidence_id, tool_run_id, event_type,
               database_name, table_name, before_json, after_json, event_time_utc,
               raw_timestamp, gtid, source_file, log_position, row_index+1, thread_id
        FROM binlog_events WHERE log_position=2338""")
    expected = case_export(connection, "case-1")["tables"]["binlog_events"]
    projection = prepare_projection(connection, "case-1", profile="full")
    try:
        exported = document(projection)
        rows = expand_document(exported)["tables"]["binlog_events"]
        assert rows == expected
        positions = [(row["source_file"], row["log_position"], row["row_index"]) for row in rows]
        assert len(set(positions)) == len(positions)
        assert {row["row_index"] for row in rows if row["log_position"] == 2338} == {0, 1}
    finally:
        projection.close()


def test_stream_checkpoints_preserve_selected_values_and_release_long_skips():
    import io
    import json
    from adapters.persistence.investigator_export import JsonMembers, STREAM_PROGRESS
    content = json.dumps({"large": [{"text": "x" * 1000}] * 2000, "selected": [1, 2]}).encode()
    normal = list(JsonMembers(io.BytesIO(content)).members(include={"selected"}))
    stream = io.BytesIO(content)
    steps = JsonMembers(stream).members(include={"selected"}, checkpoints=True)
    assert next(steps)[0] is STREAM_PROGRESS
    assert stream.tell() < len(content), "The first checkpoint must precede reading the whole container"
    steps.close()
    cooperative = list(JsonMembers(io.BytesIO(content)).members(include={"selected"}, checkpoints=True))
    assert sum(member is STREAM_PROGRESS for member, _, _ in cooperative) >= 20
    assert [row for row in cooperative if row[0] is not STREAM_PROGRESS] == normal


def test_full_reference_counts_and_origins_are_preserved():
    from adapters.persistence.investigator_export import ExportProjection
    from adapters.persistence.export_sections import resolve_sections
    from datetime import datetime, UTC
    projection = ExportProjection(profile="full", selection=resolve_sections("full", None),
        case_id="case", moment=datetime.now(UTC), redacted=False, settings={})
    try:
        projection.origin = "first"
        identifier = projection.intern("value", "repeated")["$ref"]
        for _ in range(10): projection.intern("value", "repeated")
        for index in range(4200): projection.intern("value", f"unique-{index}")
        projection.origin = "second"
        for _ in range(5): projection.intern("value", "repeated")
        value = next(item for item in projection.objects() if item["id"] == identifier)
        assert value["occurrences"] == 16
        assert value["associations"] == [{"origin": "first", "occurrences": 11}, {"origin": "second", "occurrences": 5}]
    finally:
        projection.close()


def test_validated_screen_header_avoids_a_second_analysis_scan(case, analysed):
    connection = connection_of(case)
    opened = []
    class TraceConnection:
        def execute(self, *args, **kwargs):
            return connection.execute(*args, **kwargs)
        def blobopen(self, *args, **kwargs):
            opened.append(args)
            return connection.blobopen(*args, **kwargs)
    assert list(analysis_members(TraceConnection(), "case-1", "reconciliation"))
    assert len(opened) == 1
    # Updating authoritative analysis invalidates the cached header automatically.
    stored = json.loads(connection.execute("SELECT result_json FROM analysis_results WHERE case_id='case-1' AND stage='reconciliation'").fetchone()[0])
    stored["storage_version"] = 999
    connection.execute("UPDATE analysis_results SET result_json=? WHERE case_id='case-1' AND stage='reconciliation'", (json.dumps(stored),))
    with pytest.raises(ValueError):
        list(analysis_members(TraceConnection(), "case-1", "reconciliation"))
