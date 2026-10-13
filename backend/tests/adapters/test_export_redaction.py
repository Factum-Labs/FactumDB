import copy
import json

from adapters.persistence.case_export import case_export, write_json
from adapters.persistence.export_redaction import make_redactor, redact_document
from tests.adapters.test_case_export import connection_of, stores  # noqa: F401


def test_nested_redaction_keeps_aliases_and_drops_all_sensitive_text():
    original = {
        "case_id": "case-secret",
        "tables": {
            "physical_records": [
                {
                    "values": {"email": "alice@example.com", "pin": 987654321},
                    "source_path": "C:\\Users\\Alice\\case.ibd",
                }
            ],
            "binlog_events": [
                {"before": {"email": "alice@example.com"}, "after": {"email": "alice@example.com"}}
            ],
            "analysis_results": [
                {
                    "result": {
                        "rows": [
                            {
                                "field": "email",
                                "log_display": "alice@example.com",
                                "log": 987654321,
                                "phys": 987654321,
                                "result": "Exact",
                            }
                        ],
                        "findings": [{"context": {"password": "fake-secret"}}],
                    }
                }
            ],
            "warnings": [{"message": "token=fake-token", "context": {"alice@example.com": 123}}],
            "tool_runs": [
                {"arguments": ["--password=fake-pass"], "stderr_path": "/home/alice/log"}
            ],
        },
    }
    before = copy.deepcopy(original)
    redacted = redact_document(original)
    text = json.dumps(redacted)
    for secret in [
        "alice@example.com",
        "987654321",
        "fake-secret",
        "fake-token",
        "fake-pass",
        "Alice",
        "/home/alice",
    ]:
        assert secret not in text
    physical = redacted["tables"]["physical_records"][0]["values"]
    events = redacted["tables"]["binlog_events"][0]
    assert next(iter(physical.values())) == next(iter(events["before"].values()))
    assert events["before"] == events["after"]
    comparison = redacted["tables"]["analysis_results"][0]["result"]["rows"][0]
    assert comparison["log"] == comparison["phys"] == list(physical.values())[1]
    assert comparison["log_display"] == next(iter(physical.values()))
    assert original == before
    assert redacted["case_id"] == original["case_id"]
    assert redact_document(original) != redacted


def test_typed_aliases_preserve_categories_missing_values_and_large_numbering():
    visit, alias = make_redactor(typed=True)
    projected = visit(
        {
            "case_id": "same",
            "case_name": "same",
            "table": "same",
            "field": "same",
            "evidence_id": "same",
            "tool_run_id": "same",
            "filename": "same",
            "source_file": "same",
            "source_sha256": "digest",
            "working_copy_sha256": "digest",
            "created_at": "date",
            "tool_version": "version",
            "database": "same",
            "source_path": "secret",
            "result": "Exact",
            "rule_id": "R-RECON-003",
            "count": 42,
        }
    )
    for key, category in {
        "case_id": "CASE",
        "case_name": "CASE-NAME",
        "table": "TABLE",
        "field": "FIELD",
        "evidence_id": "EVIDENCE",
        "tool_run_id": "RUN",
        "filename": "SOURCE",
        "created_at": "TIME",
        "tool_version": "VERSION",
        "database": "DATABASE",
    }.items():
        assert projected[key] == f"[{category}-001]"
    assert projected["filename"] == projected["source_file"]
    assert projected["source_sha256"] == projected["working_copy_sha256"] == "[HASH-001]"
    assert projected["source_path"] == "[REDACTED]"
    assert projected["result"] == "Exact" and projected["rule_id"] == "R-RECON-003"
    assert projected["count"] == 42
    for value in (None, "", "Unknown", "[REDACTED]"):
        assert alias(value, "SOURCE") == value
    for index in range(1, 1001):
        assert alias(f"value-{index}") == f"[VALUE-{index:03d}]"
    assert alias("same", "TABLE") == "[TABLE-001]"


def test_metadata_exceptions_do_not_apply_inside_database_images():
    visit, _ = make_redactor(typed=True)
    metadata = {
        "tool_run_id": "run-original",
        "case_id": "case-original",
        "evidence_id": "evidence-original",
        "tool_name": "custom-extractor",
        "tool_version": "9.0",
        "executable_sha256": "executable-hash",
        "stdout_sha256": "output-hash",
        "stderr_sha256": "diagnostic-hash",
        "started_at": "2026-10-13T01:00:00Z",
        "finished_at": None,
        "actor_username": "Examiner Alice",
        "actor_id": "actor-original",
        "arguments": ["--password=private"],
        "executable_path": "private-path",
        "error_message": "private diagnostic",
    }
    projected = visit(metadata, section="tool_runs")
    for key in metadata.keys() - {"arguments", "executable_path", "error_message"}:
        assert projected[key] == metadata[key]
    for key in {"arguments", "executable_path", "error_message"}:
        assert projected[key] == "[REDACTED]"
    secrets = {
        "case_name": "database-case-name",
        "examiner": "database-person",
        "tool_version": "database-version",
        "created_at": "database-time",
        "source_sha256": "database-hash",
        "case_id": "database-case",
        "tool_run_id": "database-run",
    }
    row = visit(
        {
            "case_id": "case-original",
            "values": secrets,
            "before": secrets,
            "after": secrets,
            "key_columns": ["examiner"],
            "key_values": [123456789, "database-key"],
            "provenance": {
                "evidence_id": "evidence-original",
                "tool_run_id": "run-original",
                "tool_name": "custom-extractor",
                "source_file": "private.ibd",
            },
            "context": secrets,
        },
        section="physical_records",
    )
    encoded = json.dumps(row)
    for secret in [*secrets.values(), "database-key", "123456789", "private.ibd"]:
        assert secret not in encoded
    assert row["case_id"] == "case-original"
    assert row["provenance"]["evidence_id"] == "evidence-original"
    assert row["provenance"]["tool_run_id"] == "run-original"
    assert row["provenance"]["tool_name"] == "custom-extractor"
    assert visit({"tool_version": "9.0"}, section="unrecognized")["tool_version"] != "9.0"
    missing = visit(
        {"evidence_id": None, "tool_run_id": "Unknown", "source_file": "Unknown"},
        section="physical_records",
    )
    assert missing == {"evidence_id": None, "tool_run_id": "Unknown", "source_file": "Unknown"}
    scalar = visit(
        {
            "log": {"tool_name": "mysqlbinlog", "nested": secrets},
            "phys": ["database-person", 123456789],
            "values": {"literal": "Unknown", "blank": ""},
        },
        section="tool_runs",
    )
    assert isinstance(scalar["log"], str) and scalar["log"].startswith("[VALUE-")
    assert all(str(value).startswith("[VALUE-") for value in scalar["phys"])
    assert all(value.startswith("[VALUE-") for value in scalar["values"].values())


def test_json_export_redacts_and_preserves_source(stores, tmp_path):  # noqa: F811
    connection = connection_of(stores)
    connection.execute("UPDATE cases SET case_name = 'fake-person-secret' WHERE case_id = 'case-1'")
    before = case_export(connection, "case-1")["tables"]
    path = write_json(
        connection,
        "case-1",
        tmp_path / "share.json",
        redacted=True,
        preferences={"time_mode": "utc", "utc_offset_minutes": 0},
        examiner_profile={"display_name": "fake-examiner-secret"},
    )
    text = path.read_text()
    for secret in [
        "HYPERLINK",
        "4000.10",
        "/other.ibd",
    ]:
        assert secret not in text
    assert json.loads(text)["presentation"]["examiner_profile"] == {
        "display_name": "fake-examiner-secret"
    }
    assert "redacted" in text
    assert json.loads(text)["tables"]["cases"][0]["case_name"] == "fake-person-secret"
    assert case_export(connection, "case-1")["tables"] == before
    full = write_json(connection, "case-1", tmp_path / "full.json")
    assert "fake-person-secret" in full.read_text()
