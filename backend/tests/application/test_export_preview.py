import json
import io
import sqlite3
import threading
from pathlib import Path
from io import BytesIO

import pytest
from pypdf import PdfReader

from tests.application.auth_support import authenticated_runtime
from tests.application.test_desktop_runtime import (
    call,
    create,
    evidence,
    finish,
    response,
    tools,
)


@pytest.fixture
def runtime(tmp_path):
    value = authenticated_runtime(tmp_path / "workspace")
    yield value
    value.close()


@pytest.mark.parametrize("format", ["JSON", "CSV", "PDF"])
def test_preview_selection_matches_export_and_never_writes_during_preview(
    runtime,
    tmp_path,
    monkeypatch,
    format,
):
    case_id = create(runtime, "fake-person-secret")
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    connection, stores, _ = runtime.session(case_id)
    before = stores.reports.list_by_case(case_id)
    options = {"case_id": case_id, "format": format, "sections": ["case_details"]}
    preview = call(runtime, "preview_export", **options)
    assert stores.reports.list_by_case(case_id) == before
    assert "fake-person-secret" not in "\n".join(preview["lines"])
    assert preview["pages"] >= 1
    projection = runtime.export_preview["document"]
    stream = io.StringIO()
    projection.write_json(stream)
    document = json.loads(stream.getvalue())
    assert set(document["tables"]) == {"cases"}
    assert "examiner_notes" not in document["tables"]["cases"][0]
    destination = tmp_path / ("selected" if format == "CSV" else "selected." + format.lower())
    call(
        runtime,
        "export_case",
        **options,
        path=str(destination),
        preview_token=preview["preview_token"],
    )
    if format == "JSON":
        assert json.loads(destination.read_text(encoding="utf-8")) == document
    elif format == "CSV":
        assert {p.name for p in destination.iterdir()} == {
            "cases.csv",
            "objects.csv",
            "about.txt",
        }
        assert document["case_id"] in (destination / "cases.csv").read_text()
    else:
        content = destination.read_bytes()
        assert content.startswith(b"%PDF-")
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
        assert "FORENSIC EXAMINATION REPORT" in text
        assert "EVIDENCE FILES" not in text
        assert document["case_id"] in text
        assert "fake-person-secret" not in text
    assert len(stores.reports.list_by_case(case_id)) == len(before) + 1
    assert (
        connection.execute("SELECT case_name FROM cases WHERE case_id = ?", (case_id,)).fetchone()[
            0
        ]
        == "fake-person-secret"
    )


def test_preview_invalidates_on_case_changes_options_and_expiry(runtime, tmp_path, monkeypatch):
    case_id = create(runtime)
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    options = {"case_id": case_id, "format": "PDF", "sections": ["timeline"]}
    preview = call(runtime, "preview_export", **options)
    destination = tmp_path / "bad.pdf"
    altered = {**options, "sections": ["notes"]}
    assert not response(
        runtime,
        "export_case",
        **altered,
        path=str(destination),
        preview_token=preview["preview_token"],
    )["ok"]
    call(runtime, "save_case_notes", case_id=case_id, notes="Changed after preview")
    assert not response(
        runtime,
        "export_case",
        **options,
        path=str(destination),
        preview_token=preview["preview_token"],
    )["ok"]
    preview = call(runtime, "preview_export", **options)
    runtime.export_preview["expires"] = 0
    assert not response(
        runtime,
        "export_case",
        **options,
        path=str(destination),
        preview_token=preview["preview_token"],
    )["ok"]
    assert not destination.exists()
    for sections in [[], ["unknown"], ["notes", "notes"], "notes", [123]]:
        assert not response(
            runtime, "preview_export", case_id=case_id, format="PDF", sections=sections
        )["ok"]


def test_pdf_pages_can_be_reviewed_and_boundary_is_validated(runtime, tmp_path, monkeypatch):
    case_id = create(runtime)
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    preview = call(runtime, "preview_export", case_id=case_id, format="PDF")
    assert preview["pages"] > 1
    next_page = call(runtime, "export_preview_page", preview_token=preview["preview_token"], page=2)
    assert next_page["lines"] != preview["lines"]
    assert next_page["preview_token"] == preview["preview_token"]
    assert not response(
        runtime, "export_preview_page", preview_token=preview["preview_token"], page=0
    )["ok"]


def test_disk_preview_cleanup_and_external_change_detection(runtime, tmp_path, monkeypatch):
    case_id = create(runtime)
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    preview = call(runtime, "preview_export", case_id=case_id, format="JSON")
    directory = Path(runtime.export_preview["document"].temporary.name)
    connection, _, _ = runtime.session(case_id)
    queries = []
    connection.set_trace_callback(queries.append)
    call(runtime, "export_preview_page", preview_token=preview["preview_token"], page=1)
    connection.set_trace_callback(None)
    assert not any("analysis_results" in query or "physical_records" in query for query in queries)
    database = connection.execute("PRAGMA database_list").fetchone()[2]
    other = sqlite3.connect(database)
    other.execute("UPDATE cases SET examiner_notes='External change' WHERE case_id=?", (case_id,))
    other.commit()
    other.close()
    assert not response(runtime, "export_preview_page", preview_token=preview["preview_token"], page=1)["ok"]
    assert not directory.exists()
    call(runtime, "preview_export", case_id=case_id, format="JSON")
    directory = Path(runtime.export_preview["document"].temporary.name)
    runtime.export_preview["expires"] = 0
    cleanup = threading.Thread(target=runtime._expire_export_preview)
    cleanup.start()
    cleanup.join()
    assert runtime.export_preview is None
    assert not directory.exists()
