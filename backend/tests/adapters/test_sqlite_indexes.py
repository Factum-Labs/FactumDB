"""Working on a case never makes SQLite read a whole table.

A real tablespace gives thousands of rows and a server's binlogs many
thousands of events. A query that reads a whole table to find one case's rows
gets slower with every case added, and one run once per event gets slower
with the square of the evidence. Re-decoding a binlog was such a case: the
foreign key check for each deleted event read the whole transaction_events
table.

The test records every statement the case database runs while a stage is run
again, two cases are normalized, analysed and exported, and asks SQLite how it
would run each one. Every table has to be reached through an index.
"""

from __future__ import annotations

from adapters.persistence.case_export import case_export
from core.application.models import DecodedBinlog
from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase,
    GroupTransactionsUseCase,
    ReconcileRecordsUseCase,
    ReconstructStateUseCase,
)
from core.domain.models.canonical import PhysicalRecord, TransactionMarker
from tests.adapters.test_case_scoped_reads import normalize, two_cases  # noqa: F401 - fixture
from tests.adapters.test_sqlite_binlog_events import an_event
from tests.adapters.test_sqlite_normalization import FILE, case  # noqa: F401 - fixture


def statements_run_on_a_case(stores) -> list:
    connection = stores.extraction._connection
    statements = []
    connection.set_trace_callback(statements.append)

    # A stage run again replaces what it stored the first time.
    stores.extraction.save_physical_records("case-2", "ev2-ibd", "sql-2", [
        PhysicalRecord("finance", "accounts", {"account_id": 201, "iban": "LK01"}, is_deleted=False),
    ])
    stores.extraction.save_decoded_binlog("case-2", "ev2-bin", "bin-2", DecodedBinlog(
        events=(an_event(201, position=739),),
        markers=(TransactionMarker("committed", 600, 1050, FILE, (739,)),),
    ))
    for case_id in ("case-1", "case-2"):
        normalize(stores, case_id)
        GroupTransactionsUseCase(stores.domain).execute(case_id)
        CorrelateRecordsUseCase(stores.domain).execute(case_id)
        ReconstructStateUseCase(stores.domain).execute(case_id)
        ReconcileRecordsUseCase(stores.domain).execute(case_id)
        case_export(connection, case_id)

    connection.set_trace_callback(None)
    return statements


def test_every_table_is_read_through_an_index(two_cases) -> None:
    connection = two_cases.extraction._connection
    scans = []
    for sql in statements_run_on_a_case(two_cases):
        if sql.split(None, 1)[0].upper() not in ("SELECT", "DELETE", "UPDATE"):
            continue
        for step in connection.execute("EXPLAIN QUERY PLAN " + sql):
            detail = step[3]
            # "SCAN (subquery-1)" reads a result already built, not a table.
            if detail.startswith("SCAN") and "(subquery" not in detail:
                scans.append(f"{detail}  <-  {' '.join(sql.split())}")

    assert scans == []
