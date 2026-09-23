"""The SQLite case repository: round-tripping, and the guarantees it rests on.

These tests use an in-memory database rather than a file, so they leave nothing
behind and run in milliseconds. That is the reason the repository takes an open
connection instead of a path.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_database import connect, initialise, open_case_database
from core.application.case_factory import new_case
from core.domain.models.case import Case


@pytest.fixture
def connection() -> sqlite3.Connection:
    """A fresh in-memory case database with the schema already created."""
    conn = open_case_database(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> SqliteCaseRepository:
    return SqliteCaseRepository(connection)


def a_case() -> Case:
    return new_case(case_name="finance.accounts tampering", examiner="Examiner 01")


# ── Round-tripping ───────────────────────────────────────────────────────────


def test_saved_case_comes_back_identical(repository: SqliteCaseRepository) -> None:
    """A Case written and read back must equal the original.

    Case is a frozen dataclass, so equality compares every field. If the
    datetime conversion lost precision or the timezone, this would fail.
    """
    case = a_case()
    repository.save(case)

    assert repository.find_by_id(case.case_id) == case


def test_created_at_returns_as_an_aware_datetime(
    repository: SqliteCaseRepository,
) -> None:
    """Callers get a datetime back, never the stored text.

    SQLite has no date type, so created_at is stored as text. Translating it
    back is the repository's job - nothing outside this layer should have to
    know the column is a string.
    """
    case = a_case()
    repository.save(case)

    loaded = repository.find_by_id(case.case_id)

    assert isinstance(loaded.created_at, datetime)
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == timedelta(0)


def test_timestamp_is_stored_as_iso_8601_utc(
    repository: SqliteCaseRepository, connection: sqlite3.Connection
) -> None:
    """The column holds readable, sortable text.

    ISO-8601 in UTC sorts correctly as plain text, which is why it was chosen
    over an epoch integer - someone opening the database directly can read it.
    """
    case = a_case()
    repository.save(case)

    stored = connection.execute("SELECT created_at FROM cases").fetchone()["created_at"]

    assert stored.endswith("Z")
    assert stored.startswith(str(case.created_at.year))


def test_naive_timestamp_is_treated_as_utc(repository: SqliteCaseRepository) -> None:
    """A datetime with no timezone is stored as UTC, not as local time.

    Guessing a local timezone here would put the wrong instant in the database
    with nothing to show it had happened.
    """
    case = Case(
        case_id="case-naive",
        case_name="no timezone",
        examiner="Examiner 01",
        created_at=datetime(2026, 9, 23, 10, 15, 0),
    )
    repository.save(case)

    loaded = repository.find_by_id("case-naive")

    assert loaded.created_at == datetime(2026, 9, 23, 10, 15, 0, tzinfo=timezone.utc)


# ── Lookups that find nothing ────────────────────────────────────────────────


def test_missing_case_returns_none(repository: SqliteCaseRepository) -> None:
    """"We do not have that case" is a normal answer, not an error."""
    assert repository.find_by_id("no-such-case") is None


# ── Writing the same case more than once ─────────────────────────────────────


def test_saving_the_same_case_twice_does_not_duplicate_it(
    repository: SqliteCaseRepository, connection: sqlite3.Connection
) -> None:
    """Re-running the pipeline on a case must not fail or duplicate the row."""
    case = a_case()
    repository.save(case)
    repository.save(case)

    assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


# ── Injection ────────────────────────────────────────────────────────────────


def test_injection_attempt_is_treated_as_a_plain_value(
    repository: SqliteCaseRepository, connection: sqlite3.Connection
) -> None:
    """A classic injection string must be looked up as an id, not executed.

    The queries use bound parameters, so SQLite parses the statement before the
    value is supplied and the value is never read as SQL. Built with string
    formatting instead, "' OR '1'='1" would match every row.
    """
    repository.save(a_case())

    assert repository.find_by_id("' OR '1'='1") is None
    assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


def test_quotes_in_case_fields_are_stored_verbatim(
    repository: SqliteCaseRepository,
) -> None:
    """Names containing quotes and semicolons survive unchanged."""
    case = Case(
        case_id="case-quotes",
        case_name="O'Brien; DROP TABLE cases;--",
        examiner='Examiner "01"',
        created_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    repository.save(case)

    loaded = repository.find_by_id("case-quotes")

    assert loaded.case_name == "O'Brien; DROP TABLE cases;--"
    assert loaded.examiner == 'Examiner "01"'


# ── What the connection itself guarantees ────────────────────────────────────


def test_connect_switches_foreign_keys_on(tmp_path) -> None:
    """Asserted on connect() directly, not through open_case_database().

    Going through open_case_database() would also run schema.sql, so a
    connection that never set the PRAGMA itself could still appear to pass.
    This opens an already-created database with connect() alone.
    """
    db_path = str(tmp_path / "case.db")
    open_case_database(db_path).close()

    conn = connect(db_path)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_foreign_keys_are_enforced(connection: sqlite3.Connection) -> None:
    """Foreign keys are off by default in SQLite and must be switched on.

    Without PRAGMA foreign_keys = ON every REFERENCES clause in the schema is
    parsed and then ignored, so this asserts the connection helper sets it.
    """
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO evidence_files
            VALUES ('ev-1', 'no-such-case', 'ibd', 'a.ibd', '/a.ibd',
                    1, 'hash', '/w/a.ibd', 'hash', '2026-09-23T00:00:00Z')
            """
        )


def test_schema_can_be_created_twice(connection: sqlite3.Connection) -> None:
    """Opening an existing case database must not fail.

    schema.sql uses CREATE TABLE IF NOT EXISTS for exactly this reason.
    """
    initialise(connection)
    initialise(connection)

    tables = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()[0]
    assert tables == 12
