import json
from io import BytesIO

import pytest
from pypdf import PdfReader

from adapters.persistence.export_redaction import redact_document
from adapters.persistence.export_sections import select_sections, validate_sections
from adapters.persistence.pdf_report import pdf_bytes, report_lines


def test_unselected_metadata_removed_but_business_columns_preserved():
    source = {
        "case_id": "case-1",
        "tables": {
            "physical_records": [
                {
                    "values": {"source_sha256": "business-value", "context": "data"},
                    "source_sha256": "evidence-hash",
                    "tool_run_id": "tool",
                }
            ],
            "cases": [{"case_name": "Case", "examiner_notes": "Private notes"}],
        },
    }
    selected = select_sections(source, validate_sections(["histories"]))
    text = json.dumps(selected)
    assert "evidence-hash" not in text
    assert "Private notes" not in text
    assert "business-value" in text
    assert "context" in selected["tables"]["physical_records"][0]["values"]
    assert "tool_run_id" not in selected["tables"]["physical_records"][0]
    assert source["tables"]["cases"][0]["examiner_notes"] == "Private notes"


def test_pdf_pagination_and_special_characters():
    content = pdf_bytes(["literal (parentheses) and \\backslash"] * 120)
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) == 3
    assert "literal (parentheses) and \\backslash" in reader.pages[0].extract_text()
    assert "Page 3 of 3" in reader.pages[2].extract_text()


def test_pdf_embeds_supported_unicode_and_escapes_missing_glyphs():
    document = {
        "case_id": "case-1",
        "exported_at": "2026-10-11",
        "tables": {
            "cases": [
                {"case_name": "\u0dc3\u0dd2\u0d82\u0dc4\u0dbd", "examiner_notes": "\u4e2d\u6587"}
            ],
        },
        "selection": {"sections": ["case_details", "notes"]},
    }
    lines = report_lines(document)
    assert "\u0dc3\u0dd2\u0d82\u0dc4\u0dbd" in "\n".join(lines)
    reader = PdfReader(BytesIO(pdf_bytes(lines)))
    assert len(reader.pages) >= 1
    assert "\\u4e2d\\u6587" in "\n".join(lines)


def test_pdf_contains_redacted_preview_without_original_secrets():
    document = redact_document(
        {
            "case_id": "private-case-id",
            "exported_at": "2026-10-11",
            "tables": {
                "cases": [
                    {
                        "case_name": "alice@example.com",
                        "examiner_notes": "password=fake-secret C:\\Users\\Alice\\private.db",
                    }
                ]
            },
            "selection": {"sections": ["case_details", "notes"]},
        }
    )
    lines = report_lines(document)
    reader = PdfReader(BytesIO(pdf_bytes(lines)))
    text = "\n".join(page.extract_text() for page in reader.pages)
    for secret in ["alice@example.com", "private-case-id", "fake-secret", "Alice", "private.db"]:
        assert secret not in text
        assert secret not in "\n".join(lines)
    assert document["case_id"] in text


@pytest.mark.parametrize("value", [[], ["invalid"], ["notes", "notes"], [None]])
def test_invalid_section_selection_is_rejected(value):
    with pytest.raises(ValueError):
        validate_sections(value)
