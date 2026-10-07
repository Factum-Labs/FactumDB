"""The transaction repository, and how it fits with the binlog events."""

from __future__ import annotations

import pytest

from adapters.persistence.sqlite_binlog_event_repository import SqliteBinlogEventRepository
from adapters.persistence.sqlite_transaction_repository import SqliteTransactionRepository
from core.domain.models.canonical import TransactionMarker
from tests.adapters.conftest import a_binlog, a_run
from tests.adapters.test_sqlite_binlog_events import an_event

FILE = "mysql-bin.000006"


@pytest.fixture
def transactions(connection) -> SqliteTransactionRepository:
    return SqliteTransactionRepository(connection)


@pytest.fixture
def binlog(connection) -> SqliteBinlogEventRepository:
    return SqliteBinlogEventRepository(connection)


@pytest.fixture
def stored(evidence, tool_runs, case_id) -> tuple:
    evidence.save(a_binlog(case_id, "ev-bin", FILE))
    tool_runs.save(a_run(case_id, "ev-bin"))
    return "ev-bin", "run-1"


def a_marker(start: int, positions: tuple, status: str = "committed", **extra):
    fields = dict(
        status=status,
        start_position=start,
        end_position=start + 500,
        source_file=FILE,
        event_positions=positions,
        gtid=f"cb4d5c8e-9325-11f1-9975-00155dc1157f:{start}",
        xid=50,
        thread_id=13,
    )
    fields.update(extra)
    return TransactionMarker(**fields)


def test_a_marker_round_trips(transactions, binlog, stored) -> None:
    evidence_id, run_id = stored
    binlog.save_many(
        [an_event(101, position=739), an_event(102, position=985)], evidence_id, run_id
    )
    marker = a_marker(600, (739, 985))
    transactions.save_many([marker], evidence_id, run_id)

    assert transactions.markers() == [marker]


def test_event_order_is_kept(transactions, binlog, stored) -> None:
    """The order inside a transaction is the order the changes were applied."""
    evidence_id, run_id = stored
    binlog.save_many(
        [an_event(1, position=739), an_event(2, position=985), an_event(3, position=1112)],
        evidence_id, run_id,
    )
    transactions.save_many([a_marker(600, (1112, 739, 985))], evidence_id, run_id)

    assert transactions.markers()[0].event_positions == (1112, 739, 985)


def test_a_multi_row_event_is_listed_once(transactions, binlog, stored, connection) -> None:
    """Two rows at one position are both linked, but the position comes back once."""
    evidence_id, run_id = stored
    binlog.save_many(
        [an_event(101, position=1600), an_event(103, position=1600, row_index=1)], evidence_id, run_id
    )
    transactions.save_many([a_marker(1400, (1600,))], evidence_id, run_id)

    links = connection.execute("SELECT COUNT(*) FROM transaction_events").fetchone()[0]

    assert links == 2
    assert transactions.markers()[0].event_positions == (1600,)


def test_a_marker_pointing_at_a_missing_event_is_refused(transactions, stored, connection) -> None:
    """Claiming an event we do not have is a gap, so nothing is saved."""
    evidence_id, run_id = stored
    with pytest.raises(LookupError, match="1112"):
        transactions.save_many([a_marker(600, (1112,))], evidence_id, run_id)

    assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_an_incomplete_transaction_is_kept(transactions, stored, case_id) -> None:
    """A BEGIN with no COMMIT is where the binlog we were given ends."""
    evidence_id, run_id = stored
    transactions.save_many(
        [a_marker(600, (), status="committed"), a_marker(2000, (), status="incomplete")],
        evidence_id, run_id,
    )

    incomplete = transactions.list_incomplete(case_id)

    assert [m.start_position for m in incomplete] == [2000]
    assert transactions.list_incomplete("some-other-case") == []


def test_no_gtid_is_stored_as_none(transactions, stored) -> None:
    """A server can run with GTID off. None is recorded, nothing is invented."""
    evidence_id, run_id = stored
    transactions.save_many([a_marker(600, (), gtid=None, xid=None)], evidence_id, run_id)

    loaded = transactions.markers()[0]

    assert loaded.gtid is None and loaded.xid is None


# ── Decoding the same file again ─────────────────────────────────────────────


def test_saving_markers_again_replaces_them(transactions, binlog, stored) -> None:
    evidence_id, run_id = stored
    binlog.save_many([an_event(101, position=739)], evidence_id, run_id)
    transactions.save_many([a_marker(600, (739,))], evidence_id, run_id)
    transactions.save_many([a_marker(600, (739,))], evidence_id, run_id)

    assert len(transactions.markers()) == 1


def test_events_can_be_decoded_again_after_markers_exist(transactions, binlog, stored) -> None:
    """Without clearing the links first, the foreign key blocks the re-decode."""
    evidence_id, run_id = stored
    events = [an_event(101, position=739)]
    binlog.save_many(events, evidence_id, run_id)
    transactions.save_many([a_marker(600, (739,))], evidence_id, run_id)

    binlog.save_many(events, evidence_id, run_id)
    transactions.save_many([a_marker(600, (739,))], evidence_id, run_id)

    assert transactions.markers()[0].event_positions == (739,)
