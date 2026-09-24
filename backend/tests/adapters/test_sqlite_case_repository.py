"""The SQLite case repository: round-tripping, and the guarantees it rests on."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from adapters.persistence.sqlite_database import connect, initialise, open_case_database
from core.domain.models.case import Case
from tests.adapters.conftest import FIXED_TIME, a_case


# ── Round-tripping ───────────────────────────────────────────────────────────


def test_saved_case_comes_back_identical(cases) -> None:
    """Case is a frozen dataclass, so equality compares every field.

    If the datetime conversion lost precision or the timezone, this fails.
    """
    case = a_case()
    cases.save(case)

    assert cases.find_by_id("case-1") == case


def test_get_is_the_same_lookup_as_find_by_id(cases) -> None:
    """The application's use cases call get(); the port declares find_by_id().

    Both names exist so one class satisfies both contracts while they are
    still being reconciled.
    """
    case = a_case()
    cases.save(case)

    assert cases.get("case-1") == cases.find_by_id("case-1")


def test_created_at_returns_as_an_aware_datetime(cases) -> None:
    """Callers get a datetime back, never the stored text.

    SQLite has no date type, so translating it back is this layer's job.
    """
    cases.save(a_case())

    loaded = cases.find_by_id("case-1")

    assert isinstance(loaded.created_at, datetime)
    assert loaded.created_at.utcoffset() == timedelta(0)


def test_timestamp_is_stored_as_iso_8601_utc(cases, connection) -> None:
    """The column holds readable, sortable text rather than an epoch number."""
    cases.save(a_case())

    stored = connection.execute("SELECT created_at FROM cases").fetchone()["created_at"]

    assert stored == "2026-09-23T10:00:00Z"


def test_workspace_path_survives(cases) -> None:
    """Each case owns a workspace directory, and the path is part of the case."""
    cases.save(a_case())

    assert cases.find_by_id("case-1").workspace_path == "/cases/case-1"


# ── Lookups that find nothing ────────────────────────────────────────────────


def test_missing_case_returns_none(cases) -> None:
    """"We do not have that case" is a normal answer, not an error."""
    assert cases.find_by_id("no-such-case") is None


# ── Writing the same case more than once ─────────────────────────────────────


def test_saving_the_same_case_twice_does_not_duplicate_it(cases, connection) -> None:
    """Re-running the pipeline on a case must not fail or duplicate the row."""
    cases.save(a_case())
    cases.save(a_case())

    assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


# ── Injection ────────────────────────────────────────────────────────────────


def test_injection_attempt_is_treated_as_a_plain_value(cases, connection) -> None:
    """A classic injection string is looked up as an id, not executed.

    The queries use bound parameters, so SQLite parses the statement before
    the value is supplied and the value is never read as SQL. Built with
    string formatting instead, "' OR '1'='1" would match every row.
    """
    cases.save(a_case())

    assert cases.find_by_id("' OR '1'='1") is None
    assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


def test_quotes_in_case_fields_are_stored_verbatim(cases) -> None:
    """Names containing quotes and semicolons survive unchanged."""
    case = Case(
        "case-quotes",
        "O'Brien; DROP TABLE cases;--",
        'Examiner "01"',
        FIXED_TIME,
        "/cases/case-quotes",
    )
    cases.save(case)

    loaded = cases.find_by_id("case-quotes")

    assert loaded.name == "O'Brien; DROP TABLE cases;--"
    assert loaded.examiner == 'Examiner "01"'


# ── What the connection itself guarantees ────────────────────────────────────


def test_connect_switches_foreign_keys_on(tmp_path) -> None:
    """Asserted on connect() directly, not through open_case_database().

    Going through open_case_database() would also run schema.sql, so a
    connection that never set the PRAGMA itself could still appear to pass.
    """
    db_path = str(tmp_path / "case.db")
    open_case_database(db_path).close()

    conn = connect(db_path)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_foreign_keys_are_enforced(connection) -> None:
    """Without PRAGMA foreign_keys = ON every REFERENCES clause is ignored."""
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO evidence_files
                (evidence_id, case_id, kind, filename, source_path, size_bytes,
                 source_sha256, verification_status, registered_at)
            VALUES ('ev-1', 'no-such-case', 'ibd', 'a.ibd', '/a.ibd', 1,
                    'hash', 'registered', '2026-09-23T00:00:00Z')
            """
        )


def test_schema_can_be_created_twice(connection) -> None:
    """Opening an existing case database must not fail."""
    initialise(connection)
    initialise(connection)

    tables = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()[0]
    assert tables == 12
