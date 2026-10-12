import base64
import io
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from pypdf import PdfReader

from tests.application.auth_support import authenticated_runtime
from tests.application.test_desktop_runtime import call, create, evidence, finish, response, tools


@pytest.fixture
def runtime(tmp_path):
    value = authenticated_runtime(tmp_path / "workspace")
    yield value
    value.close()


def analysed_case(runtime, tmp_path, monkeypatch):
    case_id = create(runtime, "fake-person-secret")
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    return case_id


@pytest.mark.parametrize("format", ["JSON", "PDF"])
def test_preview_is_frozen_and_export_matches(runtime, tmp_path, monkeypatch, format):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    connection, stores, _ = runtime.session(case_id)
    before = stores.reports.list_by_case(case_id)
    options = {"case_id": case_id, "format": format}
    preview = call(runtime, "preview_export", **options)
    assert stores.reports.list_by_case(case_id) == before
    document = runtime.export_preview["document"]
    if format == "JSON":
        output = io.StringIO()
        document.write_json(output)
        content = output.getvalue().encode()
        assert json.loads(content)["profile"] == "full"
        assert not json.loads(content)["selection"]["partial"]
    else:
        content = document.pdf_path.read_bytes()
        chunk = call(
            runtime,
            "export_preview_pdf",
            preview_token=preview["preview_token"],
            offset=0,
            length=262144,
        )
        assert base64.b64decode(chunk["data"]) == content[:262144]
        text = "\n".join(page.extract_text() for page in PdfReader(document.pdf_path).pages)
        assert "Investigator summary" in text and "fake-person-secret" not in text
        assert "CANONICAL" not in text
    assert preview["size_bytes"] == len(content)
    destination = tmp_path / ("selected." + format.lower())
    call(
        runtime,
        "export_case",
        **options,
        path=str(destination),
        preview_token=preview["preview_token"],
    )
    assert destination.read_bytes() == content
    assert len(stores.reports.list_by_case(case_id)) == len(before) + 1
    assert (
        connection.execute("SELECT case_name FROM cases WHERE case_id=?", (case_id,)).fetchone()[0]
        == "fake-person-secret"
    )


def test_changes_options_expiry_and_csv_are_rejected(runtime, tmp_path, monkeypatch):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    options = {"case_id": case_id, "format": "PDF"}
    preview = call(runtime, "preview_export", **options)
    destination = tmp_path / "bad.pdf"
    assert not response(
        runtime,
        "export_case",
        **options,
        redacted=False,
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
    call(runtime, "preview_export", **options)
    directory = Path(runtime.export_preview["document"].temporary.name)
    runtime.export_preview["expires"] = 0
    assert not response(
        runtime, "export_preview_page", preview_token=runtime.export_preview["token"], page=1
    )["ok"]
    assert not directory.exists()
    assert not destination.exists()
    for invalid in [
        {"format": "CSV"},
        {"format": "PDF", "profile": "full"},
        {"format": "JSON", "profile": "investigator"},
        {"format": "JSON", "sections": ["notes"]},
    ]:
        assert not response(runtime, "preview_export", case_id=case_id, **invalid)["ok"]
        assert not response(
            runtime, "export_case", case_id=case_id, path=str(destination), **invalid
        )["ok"]
    assert not destination.exists()


def test_pdf_ranges_pages_and_cached_navigation(runtime, tmp_path, monkeypatch):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    preview = call(runtime, "preview_export", case_id=case_id, format="PDF")
    token = preview["preview_token"]
    assert preview["pages"] > 1
    connection, _, _ = runtime.session(case_id)
    queries = []
    connection.set_trace_callback(queries.append)
    second = call(runtime, "export_preview_page", preview_token=token, page=2)
    call(runtime, "export_preview_pdf", preview_token=token, offset=0, length=17)
    connection.set_trace_callback(None)
    assert second["page"] == 2
    assert not any("analysis_results" in query or "physical_records" in query for query in queries)
    for page in [0, True, preview["pages"] + 1]:
        assert not response(runtime, "export_preview_page", preview_token=token, page=page)["ok"]
    for offset, length in [(-1, 1), (preview["size_bytes"], 1), (True, 1), (0, 262145), (0, 0)]:
        assert not response(
            runtime, "export_preview_pdf", preview_token=token, offset=offset, length=length
        )["ok"]
    database = connection.execute("PRAGMA database_list").fetchone()[2]
    other = sqlite3.connect(database)
    other.execute("UPDATE cases SET examiner_notes='External change' WHERE case_id=?", (case_id,))
    other.commit()
    other.close()
    assert not response(runtime, "export_preview_pdf", preview_token=token, offset=0, length=1)[
        "ok"
    ]


@pytest.mark.parametrize("format", ["JSON", "PDF"])
def test_progressive_preparation(runtime, tmp_path, monkeypatch, format):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    pending = call(runtime, "preview_export", case_id=case_id, format=format, progressive=True)
    token = pending["preparation_token"]
    for _ in range(100):
        pending = call(runtime, "export_preview_status", preparation_token=token)
        if "preview_token" in pending:
            break
    assert pending["format"] == format
    assert pending["size_bytes"] > 0
    assert runtime.export_preparation is None


@pytest.mark.parametrize("action", ["cancel", "expiry", "change", "logout", "replacement"])
@pytest.mark.parametrize("format", ["JSON", "PDF"])
def test_suspended_preparation_cleanup(runtime, tmp_path, monkeypatch, action, format):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    pending = call(runtime, "preview_export", case_id=case_id, format=format, progressive=True)
    steps = runtime.export_preparation["steps"]
    next(steps)
    child = steps.gi_yieldfrom
    directory = Path(child.gi_frame.f_locals["p"].temporary.name)
    token = pending["preparation_token"]
    if action == "cancel":
        call(runtime, "cancel_export_preview", preparation_token="stale-token")
        assert runtime.export_preparation is not None
        call(runtime, "cancel_export_preview", preparation_token=token)
    elif action == "expiry":
        runtime.export_preparation["expires"] = 0
        cleanup = threading.Thread(target=runtime._expire_export_preview)
        cleanup.start()
        cleanup.join()
    elif action == "change":
        call(runtime, "save_case_notes", case_id=case_id, notes="Changed during preparation")
        assert not response(runtime, "export_preview_status", preparation_token=token)["ok"]
    elif action == "logout":
        call(runtime, "auth_logout")
    else:
        call(runtime, "preview_export", case_id=case_id, format=format, progressive=True)
    assert not directory.exists()
