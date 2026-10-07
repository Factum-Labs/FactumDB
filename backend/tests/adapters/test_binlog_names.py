"""Binlog events are stored under the binlog's own name, not the working copy's.

The adapter names events after the file it read, which is the working copy:
"<evidence id>-mysql-bin.000001". The server's index lists "mysql-bin.000001".
The domain orders the logs by looking their names up in the index, so with the
working-copy names it found none of them and fell back to ordering by evidence
id - which, with real ids, is effectively random.

The evidence ids below are chosen so that the working-copy names sort in the
wrong order: ev-z holds mysql-bin.000001 and ev-a holds mysql-bin.000002.
"""

from __future__ import annotations

import pytest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from core.application.errors import ConflictError
from core.application.models import DecodedBinlog
from core.application.use_cases.analysis import GroupTransactionsUseCase
from core.application.use_cases.extraction import NormalizeEvidenceUseCase
from core.domain.models.canonical import AnalysisWarning, BinlogInventory, TransactionMarker
from core.domain.models.evidence import EvidenceKind
from tests.adapters.conftest import FIXED_TIME, a_binlog, a_case, a_run, an_ibd
from tests.adapters.test_sqlite_binlog_events import an_event
from tests.application.fakes import FixedClock

LOGS = {"ev-z": "mysql-bin.000001", "ev-a": "mysql-bin.000002"}


def working_copy_name(evidence_id):
    """How the filesystem adapter names a working copy."""
    return f"{evidence_id}-{LOGS[evidence_id]}"


def a_decode(evidence_id, position, account_id):
    """What the binlog adapter returns when it reads that working copy."""
    read_as = working_copy_name(evidence_id)
    return DecodedBinlog(
        events=(an_event(account_id, event_type="INSERT", position=position, source_file=read_as),),
        markers=(TransactionMarker("committed", position - 100, position + 50, read_as, (position,)),),
        warnings=(AnalysisWarning("SCHEMA_NOT_FOUND", "no schema for finance.audit",
                                  {"source_file": read_as, "log_position": "999"}),),
    )


@pytest.fixture
def stores():
    connection = open_case_database(":memory:")
    built = build_sqlite_application_stores(connection, now=lambda: FIXED_TIME)
    built.cases.save(a_case())
    for evidence_id, filename in LOGS.items():
        built.evidence.save(a_binlog("case-1", evidence_id, filename))
        built.tool_runs.save(a_run("case-1", evidence_id, f"run-{evidence_id}", tool_name="mysqlbinlog"))
    yield built
    connection.close()


def stored_names(stores, table):
    rows = stores.extraction._connection.execute(
        f"SELECT DISTINCT source_file FROM {table} ORDER BY source_file"
    ).fetchall()
    return [r[0] for r in rows]


def test_events_and_markers_are_stored_under_the_registered_name(stores) -> None:
    stores.extraction.save_decoded_binlog("case-1", "ev-z", "run-ev-z", a_decode("ev-z", 739, 101))

    assert stored_names(stores, "binlog_events") == ["mysql-bin.000001"]
    assert stored_names(stores, "transactions") == ["mysql-bin.000001"]
    links = stores.extraction._connection.execute(
        "SELECT COUNT(*) FROM transaction_events").fetchone()[0]
    assert links == 1


def test_warnings_point_at_the_registered_name_too(stores) -> None:
    stores.extraction.save_decoded_binlog("case-1", "ev-z", "run-ev-z", a_decode("ev-z", 739, 101))

    (warning,) = stores.extraction._warnings.list_by_case("case-1")

    assert warning.context["source_file"] == "mysql-bin.000001"


def test_a_decode_claiming_two_files_is_refused(stores) -> None:
    """One evidence file is one binlog; renaming a mixed bundle would hide the mix-up."""
    one, other = a_decode("ev-z", 739, 101), a_decode("ev-a", 985, 102)
    mixed = DecodedBinlog(one.events + other.events, one.markers + other.markers)

    with pytest.raises(ConflictError, match="2 files"):
        stores.extraction.save_decoded_binlog("case-1", "ev-z", "run-ev-z", mixed)

    assert stored_names(stores, "binlog_events") == []


def test_the_logs_are_ordered_by_the_servers_own_sequence(stores) -> None:
    """With the index registered, the domain finds every log and orders them
    as the server wrote them - not by evidence id."""
    stores.evidence.save(an_ibd(
        "case-1", "ev-index", kind=EvidenceKind.BINLOG_INDEX,
        source_path="/var/log/mysql/mysql-bin.index", filename="mysql-bin.index",
    ))
    stores.extraction.save_inventory("case-1", "ev-index", BinlogInventory(
        "mysql-bin.index", tuple(LOGS.values()), tuple(LOGS.values()), ()
    ))
    stores.extraction.save_decoded_binlog("case-1", "ev-a", "run-ev-a", a_decode("ev-a", 985, 102))
    stores.extraction.save_decoded_binlog("case-1", "ev-z", "run-ev-z", a_decode("ev-z", 739, 101))
    NormalizeEvidenceUseCase(stores.cases, stores.normalizer, stores.extraction, FixedClock()
                             ).execute("case-1")

    grouping = GroupTransactionsUseCase(stores.domain).execute("case-1")

    assert [t.source_file for t in grouping.transactions] == ["mysql-bin.000001", "mysql-bin.000002"]
    assert grouping.coverage.observed_files == ("mysql-bin.000001", "mysql-bin.000002")
