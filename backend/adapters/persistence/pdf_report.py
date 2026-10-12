"""Offline fpdf2 reports with embedded, open-licensed Unicode fonts."""

import json
import textwrap
from functools import cache
from itertools import islice
from pathlib import Path

from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from adapters.persistence.export_sections import report_sections
from adapters.persistence.sqlite_report_repository import SqliteReportRepository

FONTS = Path(__file__).with_name("fonts")


@cache
def _supported_characters():
    result = set()
    for filename in ("NotoSans.ttf", "NotoSansSinhala.ttf", "NotoSansTamil.ttf"):
        with TTFont(FONTS / filename) as font:
            result.update(font.getBestCmap())
    return result


def _supported_text(text):
    supported = _supported_characters()
    return "".join(
        char if ord(char) in supported else char.encode("ascii", "backslashreplace").decode("ascii")
        for char in text
    )


def _new_pdf():
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(False)
    pdf.add_font("Report", fname=FONTS / "NotoSans.ttf")
    pdf.add_font("Sinhala", fname=FONTS / "NotoSansSinhala.ttf")
    pdf.add_font("Tamil", fname=FONTS / "NotoSansTamil.ttf")
    pdf.set_fallback_fonts(["Sinhala", "Tamil"])
    pdf.set_text_shaping(True)
    pdf.set_font("Report", size=9)
    return pdf


def _style(pdf, line):
    heading = line == "FORENSIC EXAMINATION REPORT" or (
        line.partition(". ")[0].isdigit() and line.upper() == line
    )
    pdf.set_font("Report", size=10 if heading else 9)
    pdf.set_text_color(*((45, 65, 85) if heading else (25, 25, 25)))


def report_lines(document):
    """The exact text used for PDF generation and its on-screen preview.

    Supported scripts use embedded fonts. Unsupported glyphs are escaped,
    preserving their code points instead of silently dropping evidence.
    """
    case = next(iter(document["tables"].get("cases", [])), {})
    lines = [
        "FORENSIC EXAMINATION REPORT",
        str(case.get("case_name", "FactumDB selected results")),
        f"Case: {document['case_id']} | Generated: {document['exported_at']}",
        "",
    ]
    if "redaction" in document:
        lines.extend([*textwrap.wrap(document["redaction"]["note"], 90), ""])
    if document.get("selection", {}).get("partial"):
        lines.extend(["PARTIAL REPORT: only the selected sections are included.", ""])
    for section in report_sections(document):
        lines.extend([f"{section['number']}. {section['title'].upper()}", ""])
        if not section["rows"]:
            lines.append("No stored entries in this section.")
        for row in section["rows"]:
            lines.append(row["table"].replace("_", " "))
            for line in json.dumps(row["data"], indent=2, ensure_ascii=False).splitlines():
                lines.extend(
                    textwrap.wrap(line, 90, replace_whitespace=False, drop_whitespace=False) or [""]
                )
            lines.append("")
        if section["note"]:
            lines.extend(textwrap.wrap(section["note"], 90))
        lines.append("")
    pdf = _new_pdf()
    pdf.add_page()
    wrapped = []
    for line in lines:
        _style(pdf, line)
        wrapped.extend(
            pdf.multi_cell(
                w=pdf.epw,
                h=4.4,
                text=_supported_text(line),
                dry_run=True,
                output=MethodReturnValue.LINES,
            )
            or [""]
        )
    return wrapped


def pdf_bytes(lines, page_count=None):
    pdf = _new_pdf()
    if page_count is None:
        page_count = max(1, (len(lines) + 54) // 55)
    iterator = iter(lines)
    pdf.set_title("FactumDB forensic examination report")
    pdf.set_creator("FactumDB")
    for number in range(1, page_count + 1):
        page = list(islice(iterator, 55))
        pdf.add_page()
        for line in page:
            _style(pdf, line)
            pdf.cell(w=0, h=4.4, text=_supported_text(line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_y(-14)
        pdf.set_font("Report", size=8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(w=0, h=4, text=f"FactumDB | Page {number} of {page_count}", align="R")
    return bytes(pdf.output())


def write_pdf(connection, case_id, path, document, moment, **actor):
    from adapters.persistence.investigator_export import ExportProjection
    path = Path(path)
    with path.open("xb") as out:
        if isinstance(document, ExportProjection):
            if not document.line_count:
                document.prepare_lines()
            out.write(pdf_bytes(document.iter_lines(), document.pages))
        else:
            out.write(pdf_bytes(report_lines(document)))
    SqliteReportRepository(connection, now=lambda: moment).record(
        case_id, "pdf", path, [path], **actor,
    )
    return path
