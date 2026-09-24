"""The schema repository - two tables, one transaction, and the @N lookup.

This is the repository the whole binlog pipeline leans on: turning @1, @2, @3
into column names happens through schema_for(), once per row event.
"""

from __future__ import annotations

import sqlite3

import pytest

from adapters.persistence.sqlite_schema_repository import SqliteSchemaRepository
from core.domain.models.canonical import Column, Schema
from tests.adapters.conftest import a_run, an_ibd


@pytest.fixture
def schemas(connection) -> SqliteSchemaRepository:
    return SqliteSchemaRepository(connection)


@pytest.fixture
def stored(evidence, tool_runs, case_id) -> tuple:
    """Evidence and a tool run for schemas to reference."""
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd", tool_name="ibd2sdi"))
    return "ev-ibd", "run-1"


def accounts_schema() -> Schema:
    """The real finance.accounts shape, as ibd2sdi reports it."""
    return Schema(
        database="finance",
        table="accounts",
        columns=(
            Column("account_id", 1, "int", False, True),
            Column("owner", 2, "varchar(100)", True, False),
            Column("balance", 3, "int", True, False),
            Column("status", 4, "varchar(20)", True, False),
        ),
        mysql_version_id=80410,
    )


# ── Round-tripping across two tables ─────────────────────────────────────────


def test_schema_and_columns_round_trip(schemas, stored) -> None:
    evidence_id, run_id = stored
    schemas.save(accounts_schema(), evidence_id, run_id)

    assert schemas.schema_for("finance", "accounts") == accounts_schema()


def test_columns_come_back_in_position_order(schemas, stored) -> None:
    """Order is not incidental - position is what @N means.

    Saved deliberately out of order to prove the ORDER BY is doing the work
    rather than the insert order happening to be right.
    """
    evidence_id, run_id = stored
    shuffled = Schema(
        database="finance",
        table="accounts",
        columns=(
            Column("status", 4, "varchar(20)", True, False),
            Column("account_id", 1, "int", False, True),
            Column("balance", 3, "int", True, False),
            Column("owner", 2, "varchar(100)", True, False),
        ),
        mysql_version_id=80410,
    )
    schemas.save(shuffled, evidence_id, run_id)

    loaded = schemas.schema_for("finance", "accounts")

    assert [c.name for c in loaded.columns] == [
        "account_id",
        "owner",
        "balance",
        "status",
    ]


def test_the_at_n_lookup_resolves(schemas, stored) -> None:
    """What the whole binlog pipeline actually needs from this repository."""
    evidence_id, run_id = stored
    schemas.save(accounts_schema(), evidence_id, run_id)

    schema = schemas.schema_for("finance", "accounts")

    # @N is 1-based over the visible columns, so @3 is columns_in_order()[2].
    assert schema.columns_in_order()[2].name == "balance"
    assert [c.name for c in schema.primary_key_columns()] == ["account_id"]


def test_booleans_survive_as_booleans(schemas, stored) -> None:
    """SQLite has no boolean type, so the flags are stored as 0 and 1.

    They have to come back as real bools, not as the integers, or callers
    comparing with `is True` would silently get the wrong answer.
    """
    evidence_id, run_id = stored
    schemas.save(accounts_schema(), evidence_id, run_id)

    account_id = schemas.schema_for("finance", "accounts").columns_in_order()[0]

    assert account_id.is_primary_key is True
    assert account_id.is_nullable is False


# ── Missing schemas ──────────────────────────────────────────────────────────


def test_unknown_table_returns_none(schemas) -> None:
    """A binlog can name a table whose .ibd was never seized.

    That is an ordinary evidence gap, not an error, so the lookup returns
    None and the caller decides what to do about it.
    """
    assert schemas.schema_for("finance", "never_seized") is None


# ── Re-extraction ────────────────────────────────────────────────────────────


def test_the_id_is_the_same_on_a_second_extraction(schemas, stored) -> None:
    """Re-running the pipeline on the same evidence gives the same ids.

    The id is derived from the evidence and the table rather than generated,
    so two runs produce identical databases. Repeatability is one of the
    project's evaluation metrics.
    """
    evidence_id, run_id = stored

    first = schemas.save(accounts_schema(), evidence_id, run_id)
    second = schemas.save(accounts_schema(), evidence_id, run_id)

    assert first == second == "ev-ibd:finance.accounts"


def test_re_saving_does_not_duplicate_columns(schemas, stored, connection) -> None:
    evidence_id, run_id = stored
    schemas.save(accounts_schema(), evidence_id, run_id)
    schemas.save(accounts_schema(), evidence_id, run_id)

    count = connection.execute("SELECT COUNT(*) FROM schema_columns").fetchone()[0]
    assert count == 4


def test_removed_columns_do_not_linger(schemas, stored) -> None:
    """A second extraction that finds fewer columns must not leave the extras.

    Stale columns would mean @N resolving to a column that is no longer there.
    """
    evidence_id, run_id = stored
    schemas.save(accounts_schema(), evidence_id, run_id)

    shorter = Schema(
        database="finance",
        table="accounts",
        columns=(Column("account_id", 1, "int", False, True),),
        mysql_version_id=80410,
    )
    schemas.save(shorter, evidence_id, run_id)

    assert len(schemas.schema_for("finance", "accounts").columns) == 1


# ── Both tables land together ────────────────────────────────────────────────


def test_a_failed_save_leaves_nothing_behind(schemas, stored, connection) -> None:
    """The schema row and its columns are written in one transaction.

    A schema with no columns is worse than no schema: a lookup would find it
    and then resolve every @N to nothing. This forces the column insert to
    fail and checks the schema row was rolled back with it.
    """
    evidence_id, run_id = stored
    broken = Schema(
        database="finance",
        table="accounts",
        columns=(Column("account_id", 1, "int", False, True),),
        mysql_version_id=80410,
    )
    # is_nullable has a CHECK (0, 1); an out-of-range value fails the insert.
    object.__setattr__(broken.columns[0], "is_nullable", 7)

    with pytest.raises(sqlite3.IntegrityError):
        schemas.save(broken, evidence_id, run_id)

    assert connection.execute("SELECT COUNT(*) FROM schemas").fetchone()[0] == 0
    assert schemas.schema_for("finance", "accounts") is None


# ── Listing ──────────────────────────────────────────────────────────────────


def test_tables_lists_every_schema_sorted(schemas, stored) -> None:
    evidence_id, run_id = stored
    schemas.save(accounts_schema(), evidence_id, run_id)
    transfers = Schema(
        database="finance",
        table="transfers",
        columns=(Column("transfer_id", 1, "int", False, True),),
        mysql_version_id=80410,
    )
    schemas.save(transfers, evidence_id, run_id)

    assert schemas.tables() == [("finance", "accounts"), ("finance", "transfers")]
    assert len(schemas.list_by_evidence(evidence_id)) == 2


def test_schema_needs_a_real_tool_run(schemas, stored) -> None:
    """Every stored schema points at the run that produced it."""
    evidence_id, _ = stored
    with pytest.raises(sqlite3.IntegrityError):
        schemas.save(accounts_schema(), evidence_id, "no-such-run")
