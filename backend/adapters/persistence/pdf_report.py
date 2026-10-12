"""Offline fpdf2 reports with embedded, open-licensed Unicode fonts."""

import hashlib
import shutil
from datetime import datetime
from functools import cache
from pathlib import Path

import fontTools
import fpdf
import uharfbuzz
from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

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


def _new_pdf(pdf=None):
    pdf = pdf or FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(False)
    pdf.add_font("Report", fname=FONTS / "NotoSans.ttf")
    pdf.add_font("Sinhala", fname=FONTS / "NotoSansSinhala.ttf")
    pdf.add_font("Tamil", fname=FONTS / "NotoSansTamil.ttf")
    pdf.set_fallback_fonts(["Sinhala", "Tamil"])
    pdf.set_text_shaping(True)
    pdf.set_font("Report", size=9)
    return pdf


TEAL = (36, 122, 128)
NAVY = (31, 51, 69)
PALE = (239, 247, 247)
MUTED = (90, 105, 116)
COLORS = {
    "Exact": (52, 120, 85),
    "Strong": TEAL,
    "Partial": (148, 100, 0),
    "Conflicting": (179, 58, 58),
    "Unresolved": (111, 78, 146),
    "Unsupported": (104, 113, 123),
}


class SummaryPDF(FPDF):
    def header(self):
        self.set_xy(self.l_margin, 18)
        self.set_font("Report", size=8)
        self.set_text_color(*TEAL)
        self.cell(0, 4, "FactumDB  /  INVESTIGATOR SUMMARY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*TEAL)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)
        self.set_y(25)

    def footer(self):
        self.set_y(-12)
        self.set_font("Report", size=7)
        self.set_text_color(*MUTED)
        self.cell(
            0,
            4,
            f"FactumDB  |  Summary; full evidence is in JSON  |  Page {self.page_no()} of {{nb}}",
            align="C",
        )


class Layout:
    def __init__(self, pdf):
        self.pdf = pdf

    def ensure(self, height):
        if self.pdf.get_y() + height > self.pdf.h - 18:
            self.pdf.add_page()
            return True
        return False

    def heading(self, text):
        self.ensure(22)
        pdf = self.pdf
        pdf.ln(4)
        pdf.set_fill_color(*TEAL)
        pdf.rect(pdf.l_margin, pdf.get_y(), 2, 7, style="F")
        pdf.set_x(pdf.l_margin + 5)
        pdf.set_font("Report", size=12)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    def paragraph(self, text, *, size=10, color=MUTED):
        pdf = self.pdf
        pdf.set_font("Report", size=size)
        pdf.set_text_color(*color)
        # Each operation remains small even when notes contain a long unbroken string.
        text = _supported_text(str(text))
        leading = size * 0.48 + 0.6
        lines = pdf.multi_cell(pdf.epw, leading, text, dry_run=True, output=MethodReturnValue.LINES)
        for line in lines or [""]:
            self.ensure(leading)
            pdf.set_font("Report", size=size)
            pdf.set_text_color(*color)
            pdf.cell(0, leading, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def divider(self):
        self.pdf.ln(3)
        self.pdf.set_draw_color(*PALE)
        y = self.pdf.get_y()
        self.pdf.line(self.pdf.l_margin, y, self.pdf.w - self.pdf.r_margin, y)
        self.pdf.ln(3)

    def labels(self, pairs):
        pdf = self.pdf
        for label, value in pairs:
            text = _supported_text(str(value))
            pdf.set_font("Report", size=10)
            lines = pdf.multi_cell(
                pdf.epw - 49, 5.4, text, dry_run=True, output=MethodReturnValue.LINES
            ) or [""]
            for index, line in enumerate(lines):
                self.ensure(5.4)
                pdf.set_font("Report", size=10)
                pdf.set_text_color(*MUTED)
                pdf.cell(49, 5.4, label if index == 0 else "")
                pdf.set_text_color(*NAVY)
                pdf.cell(pdf.epw - 49, 5.4, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def notice(self, text):
        pdf = self.pdf
        pdf.set_font("Report", size=9)
        lines = pdf.multi_cell(
            pdf.epw - 8, 4.8, text, dry_run=True, output=MethodReturnValue.LINES
        ) or [""]
        height = len(lines) * 4.8 + 8
        self.ensure(height)
        pdf.set_font("Report", size=9)
        y = pdf.get_y()
        pdf.set_fill_color(*PALE)
        pdf.rect(pdf.l_margin, y, pdf.epw, height, style="F")
        pdf.set_text_color(*NAVY)
        for index, line in enumerate(lines):
            pdf.set_xy(pdf.l_margin + 4, y + 4 + index * 4.8)
            pdf.cell(pdf.epw - 8, 4.8, line)
        pdf.set_xy(pdf.l_margin, y + height + 3)

    def table(self, headers, widths, rows):
        pdf = self.pdf

        def draw(values, header=False, alternate=False):
            font_size = 9 if header else 9.5
            pdf.set_font("Report", size=font_size)
            numeric = [isinstance(v, int) and not isinstance(v, bool) for v in values]
            values = [
                f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else v for v in values
            ]
            wraps = [
                pdf.multi_cell(
                    width - 3,
                    4,
                    _supported_text(str(value)),
                    dry_run=True,
                    output=MethodReturnValue.LINES,
                )
                or [""]
                for width, value in zip(widths, values, strict=False)
            ]
            # Split an exceptionally tall cell across pages, preserving every line.
            remaining = max(len(lines) for lines in wraps)
            offset = 0
            while offset < remaining:
                self.ensure(10)
                pdf.set_font("Report", size=font_size)
                capacity = max(1, int((pdf.h - 18 - pdf.get_y() - 3) / 4))
                count = min(remaining - offset, capacity)
                height = count * 4 + 3
                y, x = pdf.get_y(), pdf.l_margin
                pdf.set_fill_color(*(TEAL if header else PALE if alternate else (255, 255, 255)))
                pdf.set_text_color(*((255, 255, 255) if header else NAVY))
                for column, (width, lines) in enumerate(zip(widths, wraps, strict=False)):
                    pdf.rect(x, y, width, height, style="F")
                    for line_no, line in enumerate(lines[offset : offset + count]):
                        pdf.set_xy(x + 1.5, y + 1.5 + line_no * 4)
                        pdf.cell(
                            width - 3, 4, line, align="R" if not header and numeric[column] else "L"
                        )
                    x += width
                pdf.set_xy(pdf.l_margin, y + height)
                offset += count
                if offset < remaining:
                    pdf.add_page()

        self.ensure(18)
        draw(headers, header=True)
        for index, row in enumerate(rows):
            pdf.set_font("Report", size=9.5)
            height = (
                max(
                    len(
                        pdf.multi_cell(
                            width - 3,
                            4,
                            _supported_text(str(value)),
                            dry_run=True,
                            output=MethodReturnValue.LINES,
                        )
                        or [""]
                    )
                    for width, value in zip(widths, row, strict=False)
                )
                * 4
                + 3
            )
            if self.ensure(min(height, 240) + 10):
                draw(headers, header=True)
            draw(row, alternate=index % 2 == 0)
            yield index


def renderer_manifest():
    return {
        "renderer": "fpdf2",
        "renderer_version": fpdf.__version__,
        "fonttools_version": fontTools.__version__,
        "shaping_version": uharfbuzz.__version__,
        "fonts": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(FONTS.glob("*.ttf"))
        },
    }


def render_summary_steps(document):
    """Render only grouped summary rows; yield between rows for cancellation."""
    pdf = _new_pdf(SummaryPDF(format="A4"))
    pdf.alias_nb_pages()
    pdf.set_creation_date(
        datetime.fromisoformat(document.metadata["exported_at"].replace("Z", "+00:00"))
    )
    pdf.set_title("FactumDB investigator summary")
    pdf.set_creator("FactumDB " + document.metadata["template_version"])
    document.metadata["renderer"] = renderer_manifest()
    manifest = document.metadata["renderer"]
    pdf.set_keywords(
        "; ".join(
            [
                "template=" + document.metadata["template_version"],
                "fpdf2=" + fpdf.__version__,
                "fonttools=" + fontTools.__version__,
                "uharfbuzz=" + uharfbuzz.__version__,
                *(name + "=" + sha for name, sha in sorted(manifest["fonts"].items())),
            ]
        )
    )
    pdf.add_page()
    layout = Layout(pdf)
    pdf.set_font("Report", size=21)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 12, "Investigator summary", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    case = next(document.rows("case"), {})
    layout.paragraph(case.get("case_name", "Unnamed case"), size=11, color=TEAL)
    layout.paragraph("Case: " + document.metadata["case_id"])
    layout.paragraph(
        "Prepared: " + document.metadata["exported_at"] + "  |  "
        "Template: " + document.metadata["template_version"]
    )
    if document.redacted:
        layout.notice(document.metadata["redaction"])
        layout.paragraph(
            "Alias key: CASE = case ID; CASE-NAME = case name; TABLE / DATABASE = schema "
            "identifiers; FIELD = column; EVIDENCE = evidence ID; SOURCE = filename; "
            "RUN = tool run; HASH = digest; TIME = recorded timestamp; VERSION = tool "
            "version; VALUE = other replaced text or values. Aliases apply only to this export; "
            "repeated aliases within a category refer to the same original value.",
            size=8,
            color=MUTED,
        )
    layout.labels(
        [
            ("Recorded examiner", case.get("examiner") or "Unknown"),
            ("Case registered", case.get("created_at") or "Unknown"),
            ("Analysis saved", document.metadata.get("analysed_at") or "Unknown"),
        ]
    )
    for key, value in sorted(document.metadata["examiner_profile"].items()):
        if value:
            layout.paragraph(key.replace("_", " ").title() + ": " + str(value))

    layout.heading("Classification overview")
    totals = document.metadata["classification_totals"]
    whole = sum(totals["records"].values())
    x, y = pdf.l_margin, pdf.get_y()
    for result, count in totals["records"].items():
        width = pdf.epw * count / whole if whole else 0
        pdf.set_fill_color(*COLORS[result])
        pdf.rect(x, y, width, 4, style="F")
        x += width
    pdf.set_y(y + 7)
    for _ in layout.table(
        ["Classification", "Records", "Field / presence comparisons"],
        [60, 35, 79],
        [(result, totals["records"][result], totals["fields"][result]) for result in COLORS],
    ):
        yield {"stage": "rendering classification overview", "processed": pdf.page_no()}
    layout.paragraph(
        "Exact and Strong have no individual details. Exceptional findings below are grouped, "
        "not sampled. Record and comparison counts measure different things."
    )
    layout.heading("Analysis scope")
    scope = next(document.rows("scope"), {})
    if not scope.get("recorded"):
        layout.paragraph("Analysis scope was not recorded. Complete coverage is not inferred.")
    elif scope.get("all_evidence"):
        layout.paragraph("The recorded normalization included all available evidence.")
    else:
        layout.paragraph(
            "The analysis used a restricted scope. Extracted population counts "
            "include data outside that scope; classifications concern analyzed records."
        )
        for name in scope.get("databases", []):
            layout.paragraph("Included database: " + name)
        for name in scope.get("tables", []):
            layout.paragraph("Included table: " + name)
    for row in document.rows("scope_counts"):
        layout.paragraph(
            str(row["category"])
            + ": "
            + f"{row['in_scope']:,}"
            + " in scope / "
            + f"{row['stored']:,}"
            + " stored"
        )
    layout.heading("Classification totals by table")

    def table_totals(measure):
        current = None
        counts = {}
        for row in document.rows("classification_tables"):
            if row["granularity"] != measure:
                continue
            key = (row["table"], row["granularity"])
            if current is not None and key != current:
                yield (current[0], *(counts.get(result, 0) for result in COLORS))
                counts = {}
            current = key
            counts[row["result"]] = row["count"]
        if current is not None:
            yield (current[0], *(counts.get(result, 0) for result in COLORS))

    for measure, title in [("records", "Records"), ("fields", "Field / presence comparisons")]:
        pdf.ln(3)
        layout.ensure(30)
        layout.paragraph(title, color=NAVY)
        for index in layout.table(
            ["Table", *COLORS], [35, 23, 21, 21, 24, 25, 25], table_totals(measure)
        ):
            yield {"stage": "rendering table totals", "processed": index + 1}

    sections = [
        ("Evidence inventory and recorded acquisition", "evidence"),
        ("Processing and verification", "processing"),
        ("Physical integrity", "integrity"),
        ("Schema and extraction coverage", "schemas"),
        ("Extracted physical rows", "physical"),
        ("Decoded event totals", "events"),
        ("Transaction outcomes", "transactions"),
        ("Correlation coverage", "correlation"),
        ("Reconstruction coverage", "histories"),
        ("Log coverage and missing evidence", "coverage"),
        ("Log inventory totals", "log_inventory"),
        ("Recorded coverage gaps", "coverage_gaps"),
    ]
    for title, section in sections:
        layout.heading(title)
        rows = document.rows(section)
        present = False
        for index, row in enumerate(rows):
            present = True
            if section == "evidence":
                layout.ensure(72)
                layout.paragraph(
                    str(row.get("filename", "Unknown"))
                    + "  |  "
                    + str(row.get("kind", "Unknown"))
                    + "  |  "
                    + f"{row.get('size_bytes', 0):,}"
                    + " bytes  |  "
                    + str(row.get("verification_status", "Unknown")),
                    size=11,
                    color=NAVY,
                )
                pairs = [
                    ("Evidence ID", "evidence_id"),
                    ("Source SHA-256", "source_sha256"),
                    ("Working-copy SHA-256", "working_copy_sha256"),
                    ("Recorded source", "source_path"),
                    ("Acquisition method", "acquisition_method"),
                    ("Registered", "registered_at"),
                    ("Recorded actor", "actor_username"),
                ]
                layout.labels(
                    [(label, row.get(key) or "Unknown / not recorded") for label, key in pairs]
                )
                layout.divider()
            elif section == "processing":
                layout.paragraph(
                    str(row["tool_name"])
                    + "  |  Version "
                    + str(row["tool_version"])
                    + "  |  "
                    + str(row["status"])
                    + "  |  Runs: "
                    + str(row["runs"]),
                    size=9,
                    color=NAVY,
                )
                layout.paragraph("Executable SHA-256: " + str(row["executable_sha256"]))
                layout.paragraph(
                    f"Distinct commands: {row['commands']}  |  Hashed outputs: "
                    f"{row['hashed_outputs']}  |  Hashed diagnostics: {row['hashed_diagnostics']}"
                )
                layout.paragraph(
                    "First run: "
                    + str(row["first_run"])
                    + "  |  Last completed: "
                    + str(row["last_run"] or "Unknown")
                )
            elif section == "integrity":
                layout.paragraph(
                    "Evidence "
                    + str(row["evidence_id"])
                    + "  |  "
                    + str(row["status"])
                    + "  |  Pages: "
                    + str(row["total_pages"] if row["total_pages"] is not None else "Unknown")
                    + "  |  Damaged pages: "
                    + str(row["damaged_pages"])
                )
            elif section in {"coverage", "log_inventory"}:
                label = row.get("check") or (
                    str(row.get("evidence_id")) + " / " + str(row.get("category"))
                )
                layout.paragraph(str(label) + ": " + str(row.get("value", row.get("count"))))
            elif section == "coverage_gaps":
                layout.paragraph(
                    "Rule "
                    + str(row.get("rule_id", "Unknown"))
                    + "  |  "
                    + str(row.get("reason", "Unknown limitation"))
                )
                layout.paragraph(
                    "After file: "
                    + str(row.get("after_file") or "Unknown")
                    + "  |  Position: "
                    + str(
                        row.get("after_position")
                        if row.get("after_position") is not None
                        else "Unknown"
                    )
                    + "  |  Before file: "
                    + str(row.get("before_file") or "Unknown")
                    + "  |  Missing files: "
                    + str(len(row.get("missing_files", [])))
                )
            else:
                layout.paragraph(
                    str(row["table"]) + "  /  " + str(row["category"]) + f": {row['count']:,}"
                )
            yield {"stage": "rendering " + section, "processed": index + 1}
        if not present:
            layout.paragraph("No stored observations in this section.")

    for section, title in [
        ("findings", "Exceptional comparison groups"),
        ("warnings", "Warnings and limitations"),
    ]:
        layout.heading(title)
        layout.paragraph("Rule explanations are listed once in the Rule guide below.", size=9)
        present = False
        for index, row in enumerate(document.rows(section)):
            present = True
            layout.ensure(35)
            result = row["result"] or row["severity"].title()
            layout.paragraph(
                result + "  /  " + row["table"] + (" / " + row["field"] if row["field"] else ""),
                size=11,
                color=COLORS.get(result, COLORS["Partial"]),
            )
            layout.paragraph(row["rule_id"] + " — " + row["title"], color=NAVY)
            layout.paragraph(
                f"Distinct affected records: {row['records']:,}  |  Occurrences: "
                f"{row['occurrences']:,}  |  Context variations: {row['contexts']:,}  |  "
                f"Source groups: {row['source_groups']:,}"
            )
            layout.divider()
            yield {"stage": "rendering " + section, "processed": index + 1}
        if not present:
            layout.paragraph(
                "No stored exceptional findings."
                if section == "findings"
                else "No stored warning categories. This does not prove complete coverage."
            )
    layout.heading("Rule guide")
    seen_rules = set()
    for section in ("findings", "warnings"):
        for row in document.rows(section):
            key = (row["rule_id"], row["title"], row["explanation"])
            if key in seen_rules:
                continue
            seen_rules.add(key)
            layout.ensure(35)
            layout.paragraph(row["rule_id"] + " - " + row["title"], size=11, color=NAVY)
            layout.paragraph(row["explanation"])
            layout.divider()
    if not seen_rules:
        layout.paragraph("No finding or warning rules were recorded.")
    layout.heading("Grouped source references")
    layout.paragraph("Position ranges show observed endpoints, not continuous coverage.", size=9)
    for index, row in enumerate(document.rows("finding_sources")):
        layout.ensure(40)
        layout.paragraph(
            row["rule_id"]
            + "  /  "
            + row["table"]
            + (" / " + row["field"] if row["field"] else "")
            + "  /  "
            + row["result"]
        )
        layout.paragraph(
            "Evidence: "
            + row["evidence_id"]
            + "  |  Tool run: "
            + row["tool_run_id"]
            + "  |  Source: "
            + row["source_file"]
        )
        low, high = row["first_position"], row["last_position"]
        layout.paragraph(
            "Observed locations: "
            + str(row["observed_locations"])
            + "  |  Recorded position range: "
            + (f"{low}-{high}" if low is not None else "Unknown")
            + "  |  References without positions: "
            + str(row["unknown_locations"])
        )
        layout.divider()
        yield {"stage": "rendering source references", "processed": index + 1}
    layout.heading("Examiner notes and limitations")
    layout.paragraph(case.get("examiner_notes") or "No recorded examiner notes.")
    pdf.ln(3)
    for note in document.metadata["limitations"]:
        layout.paragraph(note)
    layout.paragraph(
        "Engine revision: "
        + str(document.metadata["engine_revision"])
        + "  |  Renderer: fpdf2 "
        + fpdf.__version__
    )
    yield {"stage": "saving rendered PDF", "processed": pdf.page_no()}
    pdf.output(document.pdf_path)
    document.pages = len(pdf.pages)
    document.pdf_size = document.pdf_path.stat().st_size


def write_pdf(connection, case_id, path, document, moment, **actor):
    from adapters.persistence.summary_report import SummaryProjection

    if not isinstance(document, SummaryProjection):
        raise ValueError("PDF generation requires an investigator summary projection")
    if not document.pdf_size:
        document.prepare_pdf()
    path = Path(path)
    with path.open("xb") as output, document.pdf_path.open("rb") as source:
        shutil.copyfileobj(source, output, length=262144)
    SqliteReportRepository(connection, now=lambda: moment).record(
        case_id,
        "pdf",
        path,
        [path],
        **actor,
    )
    return path
