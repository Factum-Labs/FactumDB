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
        "UPDATE cases SET case_name='alice@example.com', examiner_notes='private-password', "
        "examiner='Recorded Examiner Alice' "
        "WHERE case_id='case-1'"
    )
    connection.execute(
        "UPDATE tool_runs SET tool_version='custom-version-9', "
        "executable_sha256='executable-original' WHERE case_id='case-1'"
    )
    profile = {
        "display_name": "Examiner Profile Alice",
        "organization": "Forensic Laboratory",
        "examiner_id": "EX-12",
        "notes": "private profile note",
    }
    summary = prepare_summary(connection, "case-1", redacted=True, examiner_profile=profile)
    try:
        summary.prepare_pdf()
        text = "\n".join(page.extract_text() for page in PdfReader(summary.pdf_path).pages)
        assert "alice@example.com" in text and "private-password" not in text
        assert "CASE-NAME" not in text
        assert "Pseudonymized" in text
        assert "Unsuitable for independent reanalysis" in " ".join(text.split())
        assert "Alias key:" in text and "case-1" in text
        assert "[S-" not in text
        for original in (
            "Recorded Examiner Alice",
            "Examiner Profile Alice",
            "EX-12",
            "Forensic Laboratory",
            "custom-version-9",
            "executable-original",
        ):
            assert original in text
        assert "private profile note" not in text
        assert summary.metadata["analysed_at"] is not None
        assert next(summary.rows("case"))["created_at"].startswith("2026-")
        assert summary.metadata["classification_totals"]["records"]
    finally:
        summary.close()


def test_typed_summary_references_connect_across_sections():
    summary = SummaryProjection("same", redacted=True, moment=WHEN, settings={})
    try:
        summary.add("case", {"case_id": "same", "case_name": "same"})
        summary.add(
            "evidence",
            {
                "evidence_id": "same",
                "filename": "same",
                "kind": "ibd",
                "source_sha256": "digest",
                "working_copy_sha256": "digest",
            },
        )
        summary.add(
            "integrity",
            {
                "evidence_id": "same",
                "status": "valid",
                "total_pages": 9,
                "damaged_pages": 0,
            },
        )
        summary.tally("same", "records", "Conflicting")
        for index in range(60):
            summary.group(
                kind="comparison",
                table="same",
                field=f"field-{index}",
                result="Conflicting",
                rule_id="R-RECON-003",
                record_id=f"row-{index}",
                identity=f"observation-{index}",
                context={},
                provenance=[
                    {
                        "evidence_id": "same",
                        "tool_run_id": "same",
                        "source_file": "same",
                        "log_position": index,
                    }
                ],
            )
        summary.group(
            kind="comparison",
            table="Unknown",
            field="",
            result="Unsupported",
            rule_id="R-CORR-020",
            context={},
        )
        summary.finish()
        evidence = next(summary.rows("evidence"))
        assert evidence["evidence_id"] == "same"
        assert next(summary.rows("integrity"))["evidence_id"] == evidence["evidence_id"]
        assert evidence["source_sha256"] == evidence["working_copy_sha256"] == "digest"
        assert next(summary.rows("classification_tables"))["table"] == "[TABLE-001]"
        for reference in summary.rows("finding_sources"):
            if reference["result"] == "Unsupported":
                assert reference["evidence_id"] == reference["source_file"] == "Unknown"
            else:
                assert reference["table"] == "[TABLE-001]"
                assert reference["evidence_id"] == evidence["evidence_id"]
                assert reference["source_file"] == evidence["filename"] == "[SOURCE-001]"
                assert reference["tool_run_id"] == "same"
                assert reference["field"].startswith("[FIELD-")
        assert summary.metadata["case_id"] == "same"
        assert next(summary.rows("case"))["case_name"] == "same"
        summary.prepare_pdf()
        reader = PdfReader(summary.pdf_path)
        assert len(reader.pages) > 1
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "[SOURCE-001]" in text and "[S-" not in text
        assert "Rule guide" in text
        assert text.count("The values differ and the log coverage for this record is complete") == 1
        assert "same" in text and "digest" in text
    finally:
        summary.close()


def test_page_breaks_restore_body_and_table_fonts():
    from adapters.persistence.pdf_report import COLORS, ColourSwatch, Layout, SummaryPDF, _new_pdf

    pdf = _new_pdf(SummaryPDF(format="A4"))
    pdf.add_page()
    layout = Layout(pdf)
    pdf.set_y(pdf.h - 19)
    layout.paragraph("A body paragraph after a page break.")
    assert pdf.page_no() == 2
    assert pdf.font_size_pt == 10
    pdf.set_y(pdf.h - 40)
    list(
        layout.table(
            ["Colour code", "Table", "Records"],
            [28, 52, 94],
            [
                (ColourSwatch(COLORS["Exact"]), f"[TABLE-{index:03d}]", 108890)
                for index in range(10)
            ],
        )
    )
    assert pdf.page_no() > 2
    assert pdf.font_size_pt == 9.5
    reader = PdfReader(io.BytesIO(pdf.output()))
    text = "\n".join(page.extract_text() for page in reader.pages)
    for page in reader.pages:
        header_positions = []

        def inspect_header(text, cm, tm, font, size, positions=header_positions):
            if "INVESTIGATOR SUMMARY" in text:
                positions.append(tm[5])

        page.extract_text(visitor_text=inspect_header)
        assert len(header_positions) == 1
        assert header_positions[0] > float(page.mediabox.height) - 15 * pdf.k
    assert text.count("108,890") == 10
    assert "[TABLE-009]" in text
    assert "ColourSwatch" not in text


@pytest.mark.parametrize("counts", [(1, 1, 1, 1, 1, 1), (15437, 11, 300, 33, 20, 1), (0,) * 6])
def test_classification_swatches_and_bar_preserve_colors_and_proportions(counts):
    from pypdf.generic import ContentStream

    from adapters.persistence.pdf_report import COLORS

    summary = SummaryProjection("case", redacted=True, moment=WHEN, settings={})
    try:
        for result, count in zip(COLORS, counts, strict=True):
            summary.db.execute(
                "INSERT INTO totals VALUES (?,?,?,?)", ("table", "records", result, count)
            )
        summary.finish()
        summary.prepare_pdf()
        reader = PdfReader(summary.pdf_path)
        text = " ".join(page.extract_text() for page in reader.pages)
        assert "Colour code" in text
        assert "Bar segment widths show the proportion of classified records" in text
        assert "ColourSwatch" not in text
        swatches, bars = [], []
        for page in reader.pages:
            fill = None
            for operands, operator in ContentStream(page.get_contents(), reader).operations:
                if operator == b"rg":
                    fill = tuple(float(value) for value in operands)
                elif operator == b"g":
                    fill = (float(operands[0]),) * 3
                elif operator == b"re":
                    width, height = map(float, operands[2:])
                    height = abs(height)
                    if abs(width - 5 * 72 / 25.4) < 0.02 and abs(height - 5 * 72 / 25.4) < 0.02:
                        swatches.append(fill)
                    if abs(height - 4 * 72 / 25.4) < 0.02:
                        bars.append((fill, width))
        expected = [
            tuple(round(component / 255, 4) for component in color) for color in COLORS.values()
        ]
        assert len(swatches) == 6
        for actual, color in zip(swatches, expected, strict=True):
            assert actual == pytest.approx(color, abs=0.00001)
        assert len(bars) == 6
        for (color, width), expected_color, count in zip(bars, expected, counts, strict=True):
            assert color == pytest.approx(expected_color, abs=0.00001)
            expected_width = 174 * 72 / 25.4 * count / sum(counts) if sum(counts) else 0
            assert width == pytest.approx(expected_width, abs=0.02)
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
