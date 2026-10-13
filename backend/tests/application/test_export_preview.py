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
        assert "Investigator summary" in text and "fake-person-secret" in text
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


def test_background_reports_coexist_and_are_reused_without_exporting(runtime, tmp_path, monkeypatch):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    stores = runtime.session(case_id)[1]
    before = stores.reports.list_by_case(case_id)
    foreground = call(runtime, "preview_export", case_id=case_id, format="PDF", redacted=False)
    for format in ("PDF", "JSON"):
        for _ in range(1000):
            result = call(runtime, "prepare_background_report", case_id=case_id, format=format)
            if "preview_token" in result:
                break
        else:
            pytest.fail("Background report did not finish")
        assert runtime.export_preview["token"] == foreground["preview_token"]
        assert result["redacted"]
    assert len(runtime._background_reports) == 2
    assert stores.reports.list_by_case(case_id) == before
    json_doc = runtime._background_reports[(case_id, "JSON")]["preview"]["document"]
    assert json.loads(json_doc.json_path.read_text())["profile"] == "full"
    assert json_doc.json_path.stat().st_size == json_doc.json_size
    directories = [Path(slot["preview"]["document"].temporary.name) for slot in runtime._background_reports.values()]
    for format in ("PDF", "JSON", "PDF"):
        claimed = call(runtime, "claim_background_report", case_id=case_id, format=format, redacted=True)
        assert claimed["format"] == format
        assert runtime.export_preview["token"] == claimed["preview_token"]
    call(runtime, "auth_lock")
    assert not runtime._background_reports
    assert all(not directory.exists() for directory in directories)


def test_background_reports_require_complete_case_and_discard_changed_snapshots(runtime, tmp_path, monkeypatch):
    case_id = create(runtime)
    assert not response(runtime, "prepare_background_report", case_id=case_id, format="PDF")["ok"]
    evidence(runtime, tmp_path, case_id)
    tools(runtime, tmp_path, monkeypatch)
    assert finish(runtime, case_id)["complete"]
    for _ in range(1000):
        result = call(runtime, "prepare_background_report", case_id=case_id, format="JSON")
        if "preview_token" in result:
            break
    directory = Path(runtime._background_reports[(case_id, "JSON")]["preview"]["document"].temporary.name)
    call(runtime, "save_case_notes", case_id=case_id, notes="New notes")
    assert call(runtime, "claim_background_report", case_id=case_id, format="JSON", redacted=True) is None
    assert not directory.exists()
    call(runtime, "prepare_background_report", case_id=case_id, format="PDF")
    job = runtime._background_reports[(case_id, "PDF")]["preparation"]
    connection = job["read_connection"]
    call(runtime, "cancel_background_reports", case_id=case_id)
    assert not runtime._background_reports
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_active_background_preparation_renews_and_foreground_adopts_it(runtime, tmp_path, monkeypatch):
    import time
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    initial = call(runtime, "prepare_background_report", case_id=case_id, format="JSON")
    slot = runtime._background_reports[(case_id, "JSON")]
    token = slot["preparation"]["token"]
    assert token == initial["preparation_token"]
    slot["preparation"]["expires"] = time.monotonic() + 5
    progressed = call(runtime, "prepare_background_report", case_id=case_id, format="JSON")
    slot = runtime._background_reports[(case_id, "JSON")]
    active = slot["preparation"] or slot["preview"]
    assert active["token"] == token
    assert active["expires"] > time.monotonic() + 590
    adopted = call(runtime, "preview_export", case_id=case_id, format="JSON", redacted=True, progressive=True)
    assert adopted.get("preparation_token", adopted.get("preview_token")) == token
    assert (case_id, "JSON") not in runtime._background_reports
    # An already queued background poll must not create a duplicate after adoption.
    background_poll = call(runtime, "prepare_background_report", case_id=case_id, format="JSON")
    assert background_poll.get("preparation_token", background_poll.get("preview_token")) == token
    assert (case_id, "JSON") not in runtime._background_reports


def test_switching_formats_retains_partial_and_finished_preview_tokens(runtime, tmp_path, monkeypatch):
    case_id = analysed_case(runtime, tmp_path, monkeypatch)
    started = []
    prepare = runtime._prepare_report_steps
    def trace(*args, **kwargs):
        started.append(args[2])
        return (yield from prepare(*args, **kwargs))
    monkeypatch.setattr(runtime, "_prepare_report_steps", trace)
    tokens = {}
    generators = {}
    for format in ("PDF", "JSON"):
        result = call(runtime, "preview_export", case_id=case_id, format=format, progressive=True, redacted=True)
        tokens[format] = result["preparation_token"]
        generators[format] = runtime.export_preparation["steps"]
        runtime.export_preview_status({"preparation_token": tokens[format]}, budget=0)
    for format in ("PDF", "JSON", "PDF", "JSON"):
        runtime.export_preview_status({"preparation_token": tokens[format]}, budget=0)
        assert runtime.export_preparation["steps"] is generators[format]
    for format in ("PDF", "JSON"):
        for _ in range(1000):
            result = call(runtime, "export_preview_status", preparation_token=tokens[format])
            if "preview_token" in result:
                break
        else:
            pytest.fail("Preparation did not complete")
        assert result["preview_token"] == tokens[format]
    assert started == ["PDF", "JSON"]
    for format in ("PDF", "JSON", "PDF"):
        result = call(runtime, "export_preview_page", preview_token=tokens[format], page=1)
        assert result["format"] == format
    call(runtime, "cancel_export_preview", preparation_token=tokens["JSON"])
    assert call(runtime, "export_preview_page", preview_token=tokens["PDF"], page=1)["format"] == "PDF"
