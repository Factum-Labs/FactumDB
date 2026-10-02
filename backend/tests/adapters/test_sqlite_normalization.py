"""Normalization and database/table filtering.

The case below has five events in five transactions across three tables:

    A  600-1050   739 finance.accounts, 985 finance.transfers   (crosses tables)
    B 1060-1150  1112 finance.transfers
    C 1250-1350  1300 finance.accounts
    D 1400-1450   (no events listed)
    E 1460-1550  1500 hr.staff                                  (no .ibd seized)
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from adapters.persistence.sqlite_normalization_repository import SqliteNormalizationRepository
from core.application.errors import ConflictError, NotFoundError
from core.application.models import DecodedBinlog, EvidenceScope, NormalizedEvidence
from core.application.use_cases.extraction import NormalizeEvidenceUseCase
from core.domain.models.canonical import Column, PhysicalRecord, Schema, TransactionMarker
from tests.adapters.conftest import FIXED_TIME, a_binlog, a_case, a_run, an_ibd
from tests.adapters.test_sqlite_binlog_events import an_event
from tests.application.fakes import FixedClock

ACCOUNTS = ("finance", "accounts")
FILE = "mysql-bin.000006"


def a_schema(table: str, key: str) -> Schema:
    return Schema("finance", table, (Column(key, 1, "int", False, True),), 80410)


def a_marker(start: int, end: int, positions: tuple) -> TransactionMarker:
    return TransactionMarker("committed", start, end, FILE, positions)


@pytest.fixture
def case():
    connection = open_case_database(":memory:")
    stores = build_sqlite_application_stores(connection, now=lambda: FIXED_TIME)
    stores.cases.save(a_case())
    stores.evidence.save(an_ibd("case-1"))
    stores.evidence.save(an_ibd("case-1", "ev-transfers", source_path="/seized/transfers.ibd",
                                filename="transfers.ibd"))
    stores.evidence.save(a_binlog("case-1", "ev-bin", FILE))
    for run_id, evidence_id, tool in [
        ("sdi-a", "ev-ibd", "ibd2sdi"), ("sql-a", "ev-ibd", "ibd2sql"),
        ("sdi-t", "ev-transfers", "ibd2sdi"), ("sql-t", "ev-transfers", "ibd2sql"),
        ("bin", "ev-bin", "mysqlbinlog"),
    ]:
        stores.tool_runs.save(a_run("case-1", evidence_id, run_id, tool_name=tool))

    save = stores.extraction
    save.save_schemas("case-1", "ev-ibd", "sdi-a", [a_schema("accounts", "account_id")])
    save.save_schemas("case-1", "ev-transfers", "sdi-t", [a_schema("transfers", "transfer_id")])
    save.save_physical_records("case-1", "ev-ibd", "sql-a", [
        PhysicalRecord("finance", "accounts", {"account_id": 101}, is_deleted=False),
        PhysicalRecord("finance", "accounts", {"account_id": 102}, is_deleted=True),
    ])
    save.save_physical_records("case-1", "ev-transfers", "sql-t", [
        PhysicalRecord("finance", "transfers", {"transfer_id": 9001}, is_deleted=False),
    ])
    save.save_decoded_binlog("case-1", "ev-bin", "bin", DecodedBinlog(
        events=(
            an_event(101, position=739),
            an_event(9001, position=985, table="transfers"),
            an_event(9001, position=1112, table="transfers"),
            an_event(103, position=1300),
            replace(an_event(7, position=1500, table="staff"), database="hr"),
        ),
        markers=(
            a_marker(600, 1050, (739, 985)),
            a_marker(1060, 1150, (1112,)),
            a_marker(1250, 1350, (1300,)),
            a_marker(1400, 1450, ()),
            a_marker(1460, 1550, (1500,)),
        ),
    ))
    yield stores
    connection.close()


def normalized_under(case, scope: EvidenceScope) -> NormalizedEvidence:
    case.scopes.save("case-1", scope)
    return case.normalizer.normalize("case-1")


def starts(markers) -> list:
    return [m.start_position for m in markers]


# ── The scope ────────────────────────────────────────────────────────────────


def test_with_no_scope_set_everything_is_in_scope(case) -> None:
    normalized = case.normalizer.normalize("case-1")

    assert [s.table for s in normalized.schemas] == ["accounts", "transfers"]
    assert len(normalized.physical_records) == 3
    assert [e.log_position for e in normalized.events] == [739, 985, 1112, 1300, 1500]
    assert starts(normalized.markers) == [600, 1060, 1250, 1400, 1460]


def test_a_table_scope_keeps_only_that_table(case) -> None:
    normalized = normalized_under(case, EvidenceScope(tables=frozenset({ACCOUNTS})))

    assert [s.table for s in normalized.schemas] == ["accounts"]
    assert {r.values["account_id"] for r in normalized.physical_records} == {101, 102}
    assert [e.log_position for e in normalized.events] == [739, 1300]


def test_a_database_scope_keeps_every_table_in_it(case) -> None:
    normalized = normalized_under(case, EvidenceScope(databases=frozenset({"finance"})))

    assert [e.log_position for e in normalized.events] == [739, 985, 1112, 1300]
    assert {e.database for e in normalized.events} == {"finance"}


# ── Transactions at the edge of the scope ────────────────────────────────────


def test_a_transaction_crossing_the_scope_keeps_only_its_in_scope_events(case) -> None:
    """A changed accounts and transfers. With only accounts in scope it must not
    claim the transfers event, which the analysis is not given."""
    normalized = normalized_under(case, EvidenceScope(tables=frozenset({ACCOUNTS})))

    a = next(m for m in normalized.markers if m.start_position == 600)

    assert a.event_positions == (739,)


def test_a_transaction_entirely_out_of_scope_is_left_out(case) -> None:
    normalized = normalized_under(case, EvidenceScope(tables=frozenset({ACCOUNTS})))

    assert starts(normalized.markers) == [600, 1250, 1400]


def test_a_transaction_listing_no_events_is_kept_whatever_the_scope(case) -> None:
    """Nothing in it says which tables it was about, so no scope can rule it out."""
    for scope in (EvidenceScope(tables=frozenset({ACCOUNTS})),
                  EvidenceScope(databases=frozenset({"hr"}))):
        assert 1400 in starts(normalized_under(case, scope).markers)


def test_filtering_never_changes_what_is_stored(case) -> None:
    """The scope narrows the analysis, never the evidence."""
    normalized_under(case, EvidenceScope(tables=frozenset({ACCOUNTS})))

    connection = case.extraction._connection
    counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("schemas", "physical_records", "binlog_events", "transactions")]
    a = connection.execute(
        "SELECT COUNT(*) FROM transaction_events te JOIN transactions t "
        "ON t.transaction_id = te.transaction_id WHERE t.start_position = 600"
    ).fetchone()[0]

    assert counts == [2, 3, 5, 5]
    assert a == 2


# ── Recording the normalization ──────────────────────────────────────────────


def test_normalizing_records_the_scope_and_what_it_kept(case) -> None:
    """Through the application's own use case: "2 of 5 events were in scope"."""
    scope = EvidenceScope(tables=frozenset({ACCOUNTS}))
    case.scopes.save("case-1", scope)

    receipt = NormalizeEvidenceUseCase(
        case.cases, case.normalizer, case.extraction, FixedClock()
    ).execute("case-1")
    record = SqliteNormalizationRepository(case.extraction._connection).find("case-1")

    assert record.scope == scope
    assert record.counts == {
        "schemas": (1, 2), "physical_records": (2, 3), "events": (2, 5), "markers": (3, 5),
    }
    assert receipt.item_count == 1 + 2 + 2 + 3


def test_the_recorded_scope_is_the_one_that_was_used(case) -> None:
    """Changing the scope afterwards must not rewrite what an analysis used."""
    accounts_only = EvidenceScope(tables=frozenset({ACCOUNTS}))
    case.scopes.save("case-1", accounts_only)
    case.extraction.save_normalized("case-1", case.normalizer.normalize("case-1"))

    case.scopes.save("case-1", EvidenceScope())
    record = SqliteNormalizationRepository(case.extraction._connection).find("case-1")

    assert record.scope == accounts_only


def test_evidence_larger_than_the_database_is_refused(case) -> None:
    """It cannot have come from this case, and the analysis reads from it."""
    too_many = NormalizedEvidence((), (), tuple(an_event(i, position=i) for i in range(6)), ())

    with pytest.raises(ConflictError, match="events"):
        case.extraction.save_normalized("case-1", too_many)


def test_a_scope_round_trips_and_defaults_to_everything(case) -> None:
    scope = EvidenceScope(databases=frozenset({"hr"}), tables=frozenset({ACCOUNTS}))

    assert case.scopes.scope_for("case-1") == EvidenceScope()
    case.scopes.save("case-1", scope)
    assert case.scopes.scope_for("case-1") == scope


def test_an_unknown_case_cannot_be_normalized(case) -> None:
    with pytest.raises(NotFoundError):
        case.normalizer.normalize("no-such-case")
