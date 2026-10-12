import io
import json

# Imported pytest fixtures are consumed through test parameters.
# ruff: noqa: F811
from collections import Counter
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader

from adapters.persistence.case_export import case_export
from adapters.persistence.investigator_export import JsonMembers
from adapters.persistence.summary_report import EXCEPTIONS, SummaryProjection, prepare_summary
from tests.adapters.test_case_export import connection_of
from tests.adapters.test_finding_provenance import analysed  # noqa: F401
from tests.adapters.test_sqlite_normalization import case  # noqa: F401

WHEN = datetime(2026, 10, 12, tzinfo=UTC)


def test_summary_preserves_totals_and_groups_without_record_values(case, analysed):
    connection = connection_of(case)
    source = next(
        row["result"]
        for row in case_export(connection, "case-1")["tables"]["analysis_results"]
        if row["stage"] == "reconciliation"
    )
    summary = prepare_summary(connection, "case-1", now=lambda: WHEN)
    try:
        assert summary.metadata["classification_totals"]["records"] == {
            result: sum(record["rollup"] == result for record in source["records"])
            for result in summary.metadata["classification_totals"]["records"]
        }
        assert summary.metadata["classification_totals"]["fields"] == {
            result: sum(field["result"] == result for field in source["rows"])
            for result in summary.metadata["classification_totals"]["fields"]
        }
        expected = Counter(
            (record["record"]["table"], field["field"], field["result"], field["rule_id"])
            for record in source["records"]
            for field in record["fields"]
            if field["result"] in EXCEPTIONS
        )
        actual = {
            (row["table"], row["field"], row["result"], row["rule_id"]): row["occurrences"]
            for row in summary.rows("findings")
            if row["field"] != "record classification"
        }
        assert actual == expected
        assert sum(
            row["records"]
            for row in summary.rows("findings")
            if row["field"] == "record classification"
        ) == sum(record["rollup"] in EXCEPTIONS for record in source["records"])
        summary.prepare_pdf()
        reader = PdfReader(summary.pdf_path)
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "Investigator summary" in text
        assert "Classification overview" in text
        assert "CANONICAL" not in text
        assert '"$ref"' not in text and "log_display" not in text
        assert "Exact and Strong have no individual details" in text
        assert len(reader.pages) == summary.pages
        first = summary.pdf_path.read_bytes()
        summary.prepare_pdf()
        assert summary.pdf_path.read_bytes() == first
    finally:
        summary.close()


def test_summary_redaction_and_unicode(case, analysed):
    connection = connection_of(case)
    connection.execute(
        "UPDATE cases SET case_name='alice@example.com', examiner_notes='private-password' "
        "WHERE case_id='case-1'"
    )
    summary = prepare_summary(connection, "case-1", redacted=True)
    try:
        summary.prepare_pdf()
        text = "\n".join(page.extract_text() for page in PdfReader(summary.pdf_path).pages)
        assert "alice@example.com" not in text and "private-password" not in text
        assert "Pseudonymized" in text and "Unsuitable for independent reanalysis" in text
        assert summary.metadata["classification_totals"]["records"]
    finally:
        summary.close()


def test_group_occurrences_contexts_and_unknown_sources_preserve_distinctions():
    summary = SummaryProjection("case", redacted=False, moment=WHEN, settings={})
    try:
        for observation, record, index, value in [
            ("a", "key=(1,2)", 0, 1),
            ("b", "key=(1,2)", 1, 2),
            ("c", "key=(3,4)", None, 3),
        ]:
            ref = {
                "evidence_id": "e",
                "tool_run_id": "t",
                "source_file": "log",
                "log_position": 100 if index is not None else None,
                "row_index": index,
            }
            for _ in range(2):
                summary.group(
                    kind="comparison",
                    table="db.table",
                    field="value",
                    result="Conflicting",
                    rule_id="R-RECON-003",
                    record_id=record,
                    identity=observation,
                    context={"variation": value},
                    provenance=[ref],
                )
        summary.finish()
        (group,) = summary.rows("findings")
        assert (group["records"], group["occurrences"], group["contexts"]) == (2, 3, 3)
        (source,) = summary.rows("finding_sources")
        assert source["observed_locations"] == 2
        assert source["unknown_locations"] == 1
        assert (source["first_position"], source["last_position"]) == (100, 100)
    finally:
        summary.close()


def test_redacted_summary_is_stable_across_fresh_preparations(case, analysed):
    connection = connection_of(case)
    documents = [
        prepare_summary(connection, "case-1", redacted=True, now=lambda: WHEN) for _ in range(2)
    ]
    try:
        for document in documents:
            document.prepare_pdf()
        assert documents[0].pdf_path.read_bytes() == documents[1].pdf_path.read_bytes()
    finally:
        for document in documents:
            document.close()


def test_unicode_and_long_notes_are_rendered_without_truncation(case, analysed):
    connection = connection_of(case)
    notes = "literal (parentheses) and \\backslash " + "longword" * 1000 + " 終中文 END-OF-NOTES"
    connection.execute(
        "UPDATE cases SET case_name=?, examiner_notes=? WHERE case_id='case-1'",
        ("සිංහල தமிழ்", notes),
    )
    summary = prepare_summary(connection, "case-1")
    try:
        summary.prepare_pdf()
        text = "\n".join(page.extract_text() for page in PdfReader(summary.pdf_path).pages)
        assert "END-OF-NOTES" in text
        assert "literal (parentheses)" in text
        assert "\\u4e2d" in text
        assert "සිංහල" in text
        assert "தமிழ்" in text
    finally:
        summary.close()


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 65536])
def test_selective_json_reader_skips_nested_images_and_escaped_strings(chunk_size):
    class Chunks(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, chunk_size))

    value = {
        "discard": [{"image": 'x\\\\x\\"{}[]' * 30, "data": [None, 1, {"a": "සිංහල"}]}],
        "records": [{"status": "committed", "events": ["large image"]}],
        "end": 12345,
    }
    reader = JsonMembers(Chunks(json.dumps(value, ensure_ascii=False).encode()))
    assert list(
        reader.members(include={"records", "end"}, item_fields={"records": {"status"}})
    ) == [
        ("records", 0, {"status": "committed"}),
        ("end", None, 12345),
    ]
