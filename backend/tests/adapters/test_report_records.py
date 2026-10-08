"""Every export is recorded in the case's report history.

A case is usually reported on more than once, and a file that was handed over
has to be checkable later. Each export written to disk gets the next version
of its format, and the SHA-256 and size of every file it wrote.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from adapters.persistence.case_export import write_csv, write_json
from core.application.errors import NotFoundError
from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase,
    GroupTransactionsUseCase,
    ReconcileRecordsUseCase,
    ReconstructStateUseCase,
)
from core.application.use_cases.extraction import NormalizeEvidenceUseCase
from tests.adapters.conftest import FIXED_TIME
from tests.adapters.test_case_export import connection_of, stores  # noqa: F401 - fixture
from tests.adapters.test_sqlite_normalization import case  # noqa: F401 - fixture
from tests.application.fakes import FixedClock


def sha256_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_json_export_is_recorded_with_the_hash_of_its_file(stores, tmp_path) -> None:
    path = write_json(connection_of(stores), "case-1", tmp_path / "case-1.json")

    (report,) = stores.reports.list_by_case("case-1")
    assert (report.format, report.version, report.location) == ("json", 1, str(path))
    assert [(f.name, f.sha256, f.size_bytes) for f in report.files] == [
        ("case-1.json", sha256_of(path), path.stat().st_size)
    ]


def test_a_csv_export_records_every_file_it_wrote(stores, tmp_path) -> None:
    folder = tmp_path / "csv"
    write_csv(connection_of(stores), "case-1", folder)

    report = stores.reports.latest("case-1", "csv")
    assert sorted(f.name for f in report.files) == sorted(p.name for p in folder.iterdir())
    assert "about.txt" in {f.name for f in report.files}
    assert all(f.sha256 == sha256_of(folder / f.name) for f in report.files)


def test_each_format_counts_its_own_versions(stores, tmp_path) -> None:
    write_json(connection_of(stores), "case-1", tmp_path / "first.json")
    write_csv(connection_of(stores), "case-1", tmp_path / "csv")
    write_json(connection_of(stores), "case-1", tmp_path / "second.json")

    assert [(r.format, r.version) for r in stores.reports.list_by_case("case-1")] == [
        ("csv", 1), ("json", 1), ("json", 2),
    ]
    assert stores.reports.latest("case-1", "json").location == str(tmp_path / "second.json")


def test_each_case_counts_its_own_versions(stores, tmp_path) -> None:
    write_json(connection_of(stores), "case-1", tmp_path / "one.json")
    write_json(connection_of(stores), "case-2", tmp_path / "two.json")

    assert stores.reports.latest("case-2", "json").version == 1
    assert [r.case_id for r in stores.reports.list_by_case("case-1")] == ["case-1"]


def test_a_report_says_which_analysis_it_shows(case, tmp_path) -> None:  # noqa: F811
    """A report made before the analysis ran shows none; one made after shows
    when the reconciliation it contains was saved."""
    connection = case.extraction._connection
    write_json(connection, "case-1", tmp_path / "before.json")

    NormalizeEvidenceUseCase(case.cases, case.normalizer, case.extraction, FixedClock()
                             ).execute("case-1")
    for stage in (GroupTransactionsUseCase, CorrelateRecordsUseCase,
                  ReconstructStateUseCase, ReconcileRecordsUseCase):
        stage(case.domain).execute("case-1")
    write_json(connection, "case-1", tmp_path / "after.json")

    before, after = case.reports.list_by_case("case-1")
    assert before.analysed_at is None
    assert after.analysed_at == FIXED_TIME


def test_the_report_history_is_not_part_of_the_export(stores, tmp_path) -> None:
    """Exporting the same case again still gives the same content."""
    first = write_json(connection_of(stores), "case-1", tmp_path / "first.json")
    second = write_json(connection_of(stores), "case-1", tmp_path / "second.json")

    contents = [json.loads(path.read_text()) for path in (first, second)]
    for content in contents:
        content.pop("exported_at")
    assert contents[0] == contents[1]


def test_a_pdf_report_is_recorded_the_same_way(stores, tmp_path) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7 report")

    record = stores.reports.record("case-1", "pdf", pdf, [pdf])

    assert (record.version, record.files[0].sha256) == (1, sha256_of(pdf))
    with pytest.raises(ValueError):
        stores.reports.record("case-1", "docx", pdf, [pdf])
    with pytest.raises(NotFoundError):
        stores.reports.record("no-such-case", "pdf", pdf, [pdf])
