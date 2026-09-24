"""The physical record repository, and the value serialisation it depends on.

This is where the recovered deleted rows are stored, so it is also where the
distinction between "deleted" and "never seized" gets decided.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.persistence._values import from_json, to_json
from adapters.persistence.sqlite_physical_record_repository import (
    SqlitePhysicalRecordRepository,
)
from core.domain.models.canonical import PhysicalRecord
from core.domain.models.values import UNOBSERVED, UndecodableValue
from tests.adapters.conftest import a_run, an_ibd


@pytest.fixture
def records(connection) -> SqlitePhysicalRecordRepository:
    return SqlitePhysicalRecordRepository(connection)


@pytest.fixture
def stored(evidence, tool_runs, case_id) -> tuple:
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd", tool_name="ibd2sql"))
    return "ev-ibd", "run-1"


def a_row(account_id: int, owner: str, balance: int, status: str,
          deleted: bool = False, **extra) -> PhysicalRecord:
    return PhysicalRecord(
        database="finance",
        table="accounts",
        values={
            "account_id": account_id,
            "owner": owner,
            "balance": balance,
            "status": status,
        },
        is_deleted=deleted,
        **extra,
    )


# ── Value serialisation ──────────────────────────────────────────────────────


def test_plain_values_round_trip() -> None:
    values = {"a": 101, "b": "Amal", "c": None, "d": True}

    assert from_json(to_json(values)) == values


def test_decimal_keeps_its_exact_value() -> None:
    """A balance written as a JSON number would come back changed.

    JSON numbers are IEEE-754 doubles and a double cannot hold every decimal
    exactly, so 4000.10 would round-trip as 4000.099999999999... Decimals are
    stored as their exact text instead. For a tool whose demonstration is
    about an account balance, that is not a detail.
    """
    values = {"balance": Decimal("4000.10")}

    loaded = from_json(to_json(values))

    assert loaded["balance"] == Decimal("4000.10")
    assert isinstance(loaded["balance"], Decimal)
    assert float(Decimal("4000.10")) != Decimal("4000.10")


def test_datetime_round_trips() -> None:
    when = datetime(2026, 8, 15, 19, 6, 25, tzinfo=timezone.utc)

    assert from_json(to_json({"opened": when}))["opened"] == when


def test_undecodable_is_not_null() -> None:
    """Decision 6: "we could not read this" is not "the database stored NULL".

    Reporting a NULL that was never in the database would be a false
    statement about the evidence, so the two must stay distinguishable
    through storage.
    """
    stored_text = to_json({"photo": UndecodableValue("BLOB not supported"), "x": None})

    loaded = from_json(stored_text)

    assert loaded["photo"] == UndecodableValue("BLOB not supported")
    assert loaded["x"] is None
    assert loaded["photo"] is not None


def test_unobserved_round_trips() -> None:
    loaded = from_json(to_json({"balance": UNOBSERVED}))

    assert loaded["balance"] is UNOBSERVED


def test_booleans_do_not_become_integers() -> None:
    """In Python True is an int, so the encoder checks bool first."""
    loaded = from_json(to_json({"flag": True, "count": 1}))

    assert loaded["flag"] is True
    assert isinstance(loaded["count"], int) and loaded["count"] == 1


def test_an_unstorable_value_is_refused() -> None:
    """Better a loud error than something silently written as its repr."""
    with pytest.raises(TypeError):
        to_json({"x": object()})


# ── Storing rows ─────────────────────────────────────────────────────────────


def test_rows_round_trip(records, stored) -> None:
    evidence_id, run_id = stored
    batch = [a_row(101, "Amal", 4000, "suspended"), a_row(103, "Kamal", 3200, "active")]
    records.save_many(batch, evidence_id, run_id)

    assert records.records_for("finance", "accounts") == batch


def test_an_empty_batch_is_a_no_op(records, stored, connection) -> None:
    evidence_id, run_id = stored
    records.save_many([], evidence_id, run_id)

    assert connection.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0] == 0


def test_page_location_survives(records, stored) -> None:
    """Where on the page a row was found, so a claim can be checked in hex."""
    evidence_id, run_id = stored
    records.save_many(
        [a_row(102, "Nimal", 7500, "active", deleted=True, page_no=4, page_offset=170)],
        evidence_id, run_id,
    )

    loaded = records.records_for("finance", "accounts")[0]

    assert (loaded.page_no, loaded.page_offset) == (4, 170)


def test_missing_page_location_stays_none(records, stored) -> None:
    """ibd2sql does not report the page, so None is the honest answer."""
    evidence_id, run_id = stored
    records.save_many([a_row(101, "Amal", 4000, "suspended")], evidence_id, run_id)

    loaded = records.records_for("finance", "accounts")[0]

    assert loaded.page_no is None and loaded.page_offset is None


# ── Live and deleted rows ────────────────────────────────────────────────────


def test_deleted_rows_are_returned_alongside_live_ones(records, stored) -> None:
    """A row surviving only as a deleted remnant is a finding, not noise.

    The reconciliation service needs to see it to say so, so records_for()
    returns both.
    """
    evidence_id, run_id = stored
    records.save_many([a_row(101, "Amal", 4000, "suspended")], evidence_id, run_id)
    records.save_many(
        [a_row(102, "Nimal", 7500, "active", deleted=True)], evidence_id, run_id
    )

    all_rows = records.records_for("finance", "accounts")

    assert len(all_rows) == 2
    assert sum(1 for r in all_rows if r.is_deleted) == 1


def test_saving_deleted_rows_does_not_wipe_the_live_ones(records, stored) -> None:
    """The two come from two separate ibd2sql runs, saved one after the other."""
    evidence_id, run_id = stored
    records.save_many(
        [a_row(101, "Amal", 4000, "suspended"), a_row(103, "Kamal", 3200, "active")],
        evidence_id, run_id,
    )
    records.save_many(
        [a_row(102, "Nimal", 7500, "active", deleted=True)], evidence_id, run_id
    )

    live = [r for r in records.records_for("finance", "accounts") if not r.is_deleted]

    assert len(live) == 2


def test_re_extraction_does_not_duplicate_rows(records, stored, connection) -> None:
    evidence_id, run_id = stored
    batch = [a_row(101, "Amal", 4000, "suspended")]
    records.save_many(batch, evidence_id, run_id)
    records.save_many(batch, evidence_id, run_id)

    assert connection.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0] == 1


def test_list_deleted_crosses_the_whole_case(records, evidence, stored, case_id) -> None:
    """One of the main things an investigator asks for, and the best demo.

    physical_records has no case_id of its own, so this joins through the
    evidence file that owns the row.
    """
    evidence_id, run_id = stored
    records.save_many([a_row(101, "Amal", 4000, "suspended")], evidence_id, run_id)
    records.save_many(
        [a_row(102, "Nimal", 7500, "active", deleted=True)], evidence_id, run_id
    )

    recovered = records.list_deleted(case_id)

    assert [r.values["owner"] for r in recovered] == ["Nimal"]
    assert records.list_deleted("some-other-case") == []


# ── Telling "deleted" apart from "never seized" ──────────────────────────────


def test_tables_with_physical_evidence(records, stored) -> None:
    """Without this, "row not found" would mean two different things.

    A row can be missing because it was deleted, or missing because nobody
    seized that table's tablespace. Collapsing the two would let the tool
    report a deletion that never happened.
    """
    evidence_id, run_id = stored
    records.save_many([a_row(101, "Amal", 4000, "suspended")], evidence_id, run_id)

    held = records.tables_with_physical_evidence()

    assert ("finance", "accounts") in held
    assert ("finance", "transfers") not in held


# ── Referential integrity ────────────────────────────────────────────────────


def test_rows_need_a_real_tool_run(records, stored) -> None:
    """Every stored row points at the run that produced it."""
    evidence_id, _ = stored
    with pytest.raises(sqlite3.IntegrityError):
        records.save_many([a_row(101, "Amal", 4000, "suspended")], evidence_id, "no-run")
