import copy
import json

from adapters.persistence.case_export import case_export, write_csv, write_json
from adapters.persistence.export_redaction import redact_document
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
        "case-secret",
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
    assert redact_document(original) != redacted


def test_both_exports_redact_and_preserve_source(stores, tmp_path):  # noqa: F811
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
    csv_files = write_csv(
        connection,
        "case-1",
        tmp_path / "share-csv",
        redacted=True,
        preferences={"time_mode": "utc", "utc_offset_minutes": 0},
        examiner_profile={"display_name": "fake-examiner-secret"},
    )
    text = (
        path.read_text()
        + "".join(p.read_text() for p in csv_files)
        + (tmp_path / "share-csv/about.txt").read_text()
    )
    for secret in [
        "fake-person-secret",
        "fake-examiner-secret",
        "HYPERLINK",
        "4000.10",
        "/other.ibd",
    ]:
        assert secret not in text
    assert "redacted" in text
    assert case_export(connection, "case-1")["tables"] == before
    full = write_json(connection, "case-1", tmp_path / "full.json")
    assert "fake-person-secret" in full.read_text()
