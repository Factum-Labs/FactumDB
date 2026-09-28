"""The integrity, warning and binlog inventory repositories.

Three small tables, together here because each one is about what the tool
could not see rather than what it found: damaged pages, skipped input, and
missing logs.
"""

from __future__ import annotations

import sqlite3

import pytest

from adapters.persistence.sqlite_binlog_inventory_repository import (
    SqliteBinlogInventoryRepository,
)
from adapters.persistence.sqlite_integrity_repository import SqliteIntegrityRepository
from adapters.persistence.sqlite_schema_repository import SqliteSchemaRepository
from adapters.persistence.sqlite_warning_repository import SqliteWarningRepository
from core.domain.models.canonical import (
    AnalysisWarning,
    BinlogInventory,
    Column,
    IntegrityResult,
    Schema,
)
from core.domain.models.evidence import EvidenceKind
from tests.adapters.conftest import FIXED_TIME, a_run, an_ibd


def a_result(status: str = "valid", damaged: int = 0) -> IntegrityResult:
    return IntegrityResult(
        total_pages=7,
        damaged_pages=damaged,
        status=status,
        page_counts={"Index page": 1, "Undo log page": 0, "Freshly allocated page": 3},
        raw_summary="File::accounts.ibd ...",
    )


def accounts_schema() -> Schema:
    return Schema(
        database="finance",
        table="accounts",
        columns=(Column("account_id", 1, "int", False, True),),
        mysql_version_id=80410,
    )


@pytest.fixture
def stored_ibd(evidence, tool_runs, case_id) -> tuple:
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd", tool_name="innochecksum"))
    return "ev-ibd", "run-1"


# ── Integrity ────────────────────────────────────────────────────────────────


@pytest.fixture
def integrity(connection) -> SqliteIntegrityRepository:
    return SqliteIntegrityRepository(connection)


def test_integrity_round_trips_with_its_zeros(integrity, stored_ibd) -> None:
    """"Undo log page: 0" is why the old balance cannot be recovered."""
    evidence_id, run_id = stored_ibd
    integrity.save(a_result(), evidence_id, run_id)

    loaded = integrity.find_by_evidence(evidence_id)

    assert loaded == a_result()
    assert loaded.page_counts["Undo log page"] == 0


def test_checking_a_file_again_replaces_the_result(integrity, stored_ibd) -> None:
    evidence_id, run_id = stored_ibd
    integrity.save(a_result(), evidence_id, run_id)
    integrity.save(a_result("damaged", damaged=1), evidence_id, run_id)

    assert integrity.find_by_evidence(evidence_id).status == "damaged"


def test_integrity_is_found_by_table_through_its_schema(
    integrity, stored_ibd, connection
) -> None:
    evidence_id, run_id = stored_ibd
    integrity.save(a_result(), evidence_id, run_id)
    SqliteSchemaRepository(connection).save(accounts_schema(), evidence_id, run_id)

    assert integrity.integrity_for("finance", "accounts") == a_result()
    assert integrity.integrity_for("finance", "transfers") is None


def test_without_a_schema_the_table_cannot_be_matched(integrity, stored_ibd) -> None:
    """None, not "damaged": the file exists but is not yet tied to a table."""
    evidence_id, run_id = stored_ibd
    integrity.save(a_result(), evidence_id, run_id)

    assert integrity.integrity_for("finance", "accounts") is None


def test_list_damaged_leaves_out_valid_and_unknown(
    integrity, evidence, tool_runs, stored_ibd, case_id
) -> None:
    """'unknown' means the summary was unreadable, not that a page failed."""
    evidence_id, run_id = stored_ibd
    evidence.save(an_ibd(case_id, "ev-2", source_path="/b.ibd", filename="b.ibd"))
    evidence.save(an_ibd(case_id, "ev-3", source_path="/c.ibd", filename="c.ibd"))
    integrity.save(a_result("damaged", damaged=1), evidence_id, run_id)
    integrity.save(a_result("valid"), "ev-2", run_id)
    integrity.save(a_result("unknown"), "ev-3", run_id)

    damaged = integrity.list_damaged(case_id)

    assert [r.status for r in damaged] == ["damaged"]


def test_integrity_needs_a_real_tool_run(integrity, stored_ibd) -> None:
    evidence_id, _ = stored_ibd
    with pytest.raises(sqlite3.IntegrityError):
        integrity.save(a_result(), evidence_id, "no-run")


# ── Warnings ─────────────────────────────────────────────────────────────────


@pytest.fixture
def warnings(connection) -> SqliteWarningRepository:
    return SqliteWarningRepository(connection, now=lambda: FIXED_TIME)


def a_warning(code: str = "SCHEMA_NOT_FOUND", table: str = "transfers") -> AnalysisWarning:
    return AnalysisWarning(
        code=code,
        message=f"no schema for finance.{table}",
        context={"table": f"finance.{table}"},
    )


def test_warnings_round_trip_in_order(warnings, stored_ibd, case_id) -> None:
    evidence_id, run_id = stored_ibd
    batch = [a_warning(table="transfers"), a_warning("COLUMN_POSITION_UNKNOWN", "audit")]
    warnings.save_many(batch, case_id, evidence_id, run_id)

    assert warnings.list_by_case(case_id) == batch


def test_a_case_level_warning_needs_no_file(warnings, case_id) -> None:
    """Some warnings are about the whole case, so the file and run are optional."""
    warnings.save_many([a_warning("UNVALIDATED_MYSQL_VERSION")], case_id)

    assert [w.code for w in warnings.list_by_case(case_id)] == ["UNVALIDATED_MYSQL_VERSION"]


def test_warnings_are_added_not_replaced(warnings, case_id) -> None:
    """Nothing identifies "the same warning" twice, so nothing is overwritten."""
    warnings.save_many([a_warning()], case_id)
    warnings.save_many([a_warning()], case_id)

    assert len(warnings.list_by_case(case_id)) == 2


def test_list_by_code_filters(warnings, case_id) -> None:
    warnings.save_many(
        [a_warning("SCHEMA_NOT_FOUND"), a_warning("COLUMN_POSITION_UNKNOWN")], case_id
    )

    found = warnings.list_by_code(case_id, "SCHEMA_NOT_FOUND")

    assert [w.code for w in found] == ["SCHEMA_NOT_FOUND"]


def test_warnings_stay_in_their_case(warnings, cases, case_id) -> None:
    from tests.adapters.conftest import a_case

    cases.save(a_case("case-2"))
    warnings.save_many([a_warning()], case_id)

    assert warnings.list_by_case("case-2") == []


def test_a_warning_needs_a_real_case(warnings) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        warnings.save_many([a_warning()], "no-such-case")


# ── Binlog inventory ─────────────────────────────────────────────────────────


@pytest.fixture
def inventories(connection) -> SqliteBinlogInventoryRepository:
    return SqliteBinlogInventoryRepository(connection)


@pytest.fixture
def stored_index(evidence, case_id) -> str:
    evidence.save(
        an_ibd(
            case_id,
            "ev-index",
            kind=EvidenceKind.BINLOG_INDEX,
            source_path="/var/log/mysql/mysql-bin.index",
            filename="mysql-bin.index",
        )
    )
    return "ev-index"


def test_no_index_file_means_none(inventories) -> None:
    """None means "cannot tell", which is weaker than "nothing missing"."""
    assert inventories.inventory() is None


def test_missing_files_are_worked_out_on_save(inventories, stored_index) -> None:
    """The caller's missing list is not trusted; listed minus present is."""
    inventories.save(
        BinlogInventory(
            index_file="mysql-bin.index",
            listed_files=(
                "/var/log/mysql/mysql-bin.000005",
                "/var/log/mysql/mysql-bin.000006",
            ),
            present_files=("mysql-bin.000006",),
            missing_files=(),
        ),
        stored_index,
    )

    loaded = inventories.inventory()

    assert loaded.missing_files == ("mysql-bin.000005",)
    assert loaded.listed_files == ("mysql-bin.000005", "mysql-bin.000006")


def test_nothing_missing_is_an_empty_list(inventories, stored_index) -> None:
    inventories.save(
        BinlogInventory("mysql-bin.index", ("mysql-bin.000006",), ("mysql-bin.000006",), ()),
        stored_index,
    )

    assert inventories.find_by_evidence(stored_index).missing_files == ()
