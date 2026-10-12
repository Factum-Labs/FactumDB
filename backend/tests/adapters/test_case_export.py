"""Exporting a case as JSON for checking outside FactumDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.persistence.case_export import case_export, write_json
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from core.application.errors import NotFoundError
from core.application.models import DecodedBinlog
from core.domain.models.canonical import BinlogEvent, Column, PhysicalRecord, Schema
from core.domain.models.values import UndecodableValue
from tests.adapters.conftest import FIXED_TIME, a_binlog, a_case, a_run, an_ibd
from tests.adapters.test_sqlite_normalization import case  # noqa: F401 - fixture

WHEN = datetime(2026, 10, 3, 3, 45, tzinfo=timezone.utc)
PAYMENTS = Schema("shop", "payments", (
    Column("payment_id", 1, "int", False, True),
    Column("amount", 2, "decimal(12,2)", False, False),
    Column("note", 3, "text", True, False),
    Column("photo", 4, "blob", True, False),
), 80411)
AMAL = {"payment_id": 1, "amount": Decimal("4000.10"), "note": '=HYPERLINK("http://x")',
        "photo": UndecodableValue("binary data is not decoded")}
NIMAL = {"payment_id": 2, "amount": Decimal("7500.50"), "note": None, "photo": None}


def an_event(event_type, position, before, after):
    return BinlogEvent(event_type=event_type, database="shop", table="payments",
                       before=before, after=after, timestamp=WHEN,
                       raw_timestamp="261003  9:15:00", log_position=position,
                       source_file="mysql-bin.000044", gtid=None, thread_id=8)


@pytest.fixture
def stores():
    connection = open_case_database(":memory:")
    built = build_sqlite_application_stores(connection, now=lambda: FIXED_TIME)
    for case_id in ("case-1", "case-2"):
        built.cases.save(a_case(case_id))
    built.evidence.save(an_ibd("case-1"))
    built.evidence.save(a_binlog("case-1", "ev-bin", "mysql-bin.000044"))
    built.evidence.save(an_ibd("case-2", "ev-other", source_path="/other.ibd", filename="other.ibd"))
    for case_id, evidence_id, run_id, tool in [
        ("case-1", "ev-ibd", "sdi", "ibd2sdi"), ("case-1", "ev-ibd", "sql", "ibd2sql"),
        ("case-1", "ev-bin", "bin", "mysqlbinlog"), ("case-2", "ev-other", "sql-2", "ibd2sql"),
    ]:
        built.tool_runs.save(a_run(case_id, evidence_id, run_id, tool_name=tool))

    save = built.extraction
    save.save_schemas("case-1", "ev-ibd", "sdi", [PAYMENTS])
    save.save_physical_records("case-1", "ev-ibd", "sql", [
        PhysicalRecord("shop", "payments", AMAL, is_deleted=False),
        PhysicalRecord("shop", "payments", NIMAL, is_deleted=True),
    ])
    save.save_decoded_binlog("case-1", "ev-bin", "bin", DecodedBinlog(events=(
        an_event("INSERT", 2338, None, AMAL),
        an_event("UPDATE", 5944, {"payment_id": 1}, {"note": "checked"}),   # MINIMAL image
        an_event("DELETE", 6700, NIMAL, None),
    ), markers=()))
    save.save_physical_records("case-2", "ev-other", "sql-2", [
        PhysicalRecord("shop", "payments", {"payment_id": 99}, is_deleted=False),
    ])
    yield built
    connection.close()


def connection_of(stores):
    return stores.extraction._connection



def test_the_json_export_holds_every_table_for_this_case_only(stores) -> None:
    tables = case_export(connection_of(stores), "case-1")["tables"]

    assert len(tables) == 17
    assert [r["record_id"].split(":")[0] for r in tables["physical_records"]] == ["ev-ibd", "ev-ibd"]
    assert {r["evidence_id"] for r in tables["evidence_files"]} == {"ev-ibd", "ev-bin"}
    assert len(tables["binlog_events"]) == 3


def test_json_values_keep_their_types_and_their_provenance(stores) -> None:
    """A checker must be able to tell 4000.10 the DECIMAL from "4000.10" the text,
    and follow every row back to the run that produced it."""
    records = case_export(connection_of(stores), "case-1")["tables"]["physical_records"]
    record = next(r for r in records if r["values"]["payment_id"] == 1)

    assert record["values"]["amount"] == {"__decimal__": "4000.10"}
    assert record["tool_run_id"] == "sql"
    assert "values_json" not in record


def test_the_same_case_exports_the_same_way_every_time(stores) -> None:
    first = case_export(connection_of(stores), "case-1")
    second = case_export(connection_of(stores), "case-1")

    first.pop("exported_at"), second.pop("exported_at")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_an_unknown_case_cannot_be_exported(stores) -> None:
    with pytest.raises(NotFoundError):
        case_export(connection_of(stores), "no-such-case")


def test_an_export_never_overwrites_an_earlier_one(stores, tmp_path) -> None:
    write_json(connection_of(stores), "case-1", tmp_path / "case-1.json")

    with pytest.raises(FileExistsError):
        write_json(connection_of(stores), "case-1", tmp_path / "case-1.json")


@pytest.mark.parametrize("options", [{"sections": ["notes"]}, {"profile": "investigator"}])
def test_json_writer_rejects_partial_case_options(stores, tmp_path, options):
    destination = tmp_path / "partial.json"
    with pytest.raises(ValueError):
        write_json(connection_of(stores), "case-1", destination, **options)
    assert not destination.exists()
