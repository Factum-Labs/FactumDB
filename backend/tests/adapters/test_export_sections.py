import json

import pytest

from adapters.persistence.export_sections import select_sections, validate_sections


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


@pytest.mark.parametrize("value", [[], ["invalid"], ["notes", "notes"], [None]])
def test_invalid_section_selection_is_rejected(value):
    with pytest.raises(ValueError):
        validate_sections(value)
