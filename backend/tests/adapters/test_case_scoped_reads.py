"""Two cases in one case database never see each other's evidence.

Rows belong to a case only through their evidence file, so every read made
for a case has to follow that link. The second case is built to make any leak
show: a table with the same name but different columns, a binlog with the same
file name, and an event at the same log position as the first case.

    case-1   finance.accounts (account_id)         mysql-bin.000006 @739 ...
    case-2   finance.accounts (account_id, iban)   mysql-bin.000006 @739

case-2 is stored last, so a read that ignored the case would pick up its
schema, its integrity result and its binlog inventory for case-1 as well.
"""

from __future__ import annotations

import pytest

from adapters.persistence.sqlite_normalization_repository import SqliteNormalizationRepository
from core.application.models import DecodedBinlog
from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase,
    GroupTransactionsUseCase,
    ReconcileRecordsUseCase,
    ReconstructStateUseCase,
)
from core.application.use_cases.extraction import NormalizeEvidenceUseCase
from core.domain.models.canonical import (
    BinlogInventory, Column, IntegrityResult, PhysicalRecord, Schema, TransactionMarker,
)
from core.domain.models.evidence import EvidenceKind, ToolRunStatus
from tests.adapters.conftest import a_binlog, a_case, a_run, an_ibd
from tests.adapters.test_finding_provenance import references_in
from tests.adapters.test_sqlite_binlog_events import an_event
from tests.adapters.test_sqlite_normalization import FILE, case  # noqa: F401 - fixture
from tests.application.fakes import FixedClock

OWN_FILES = {
    "case-1": {"ev-ibd", "ev-transfers", "ev-bin"},
    "case-2": {"ev2-ibd", "ev2-bin", "ev2-index"},
}


@pytest.fixture
def two_cases(case):
    """The normalization tests' case, plus a second case in the same database."""
    # case-1's accounts.ibd failed its page check.
    case.tool_runs.save(a_run("case-1", "ev-ibd", "check-1", tool_name="innochecksum",
                              status=ToolRunStatus.FAILED, exit_code=1))
    case.extraction.save_integrity("case-1", "ev-ibd", "check-1",
                                   IntegrityResult(total_pages=7, damaged_pages=1, status="damaged"))

    case.cases.save(a_case("case-2"))
    case.evidence.save(an_ibd("case-2", "ev2-ibd"))
    case.evidence.save(a_binlog("case-2", "ev2-bin", FILE))
    case.evidence.save(an_ibd("case-2", "ev2-index", kind=EvidenceKind.BINLOG_INDEX,
                              source_path="/var/log/mysql/mysql-bin.index",
                              filename="mysql-bin.index"))
    for run_id, evidence_id, tool in [
        ("sdi-2", "ev2-ibd", "ibd2sdi"), ("sql-2", "ev2-ibd", "ibd2sql"),
        ("check-2", "ev2-ibd", "innochecksum"), ("bin-2", "ev2-bin", "mysqlbinlog"),
    ]:
        case.tool_runs.save(a_run("case-2", evidence_id, run_id, tool_name=tool))

    save = case.extraction
    save.save_integrity("case-2", "ev2-ibd", "check-2",
                        IntegrityResult(total_pages=7, damaged_pages=0, status="valid"))
    save.save_schemas("case-2", "ev2-ibd", "sdi-2", [Schema("finance", "accounts", (
        Column("account_id", 1, "int", False, True),
        Column("iban", 2, "varchar(34)", True, False),
    ), 80410)])
    save.save_physical_records("case-2", "ev2-ibd", "sql-2", [
        PhysicalRecord("finance", "accounts", {"account_id": 201, "iban": "LK01"}, is_deleted=False),
    ])
    save.save_decoded_binlog("case-2", "ev2-bin", "bin-2", DecodedBinlog(
        events=(an_event(201, position=739),),
        markers=(TransactionMarker("committed", 600, 1050, FILE, (739,)),),
    ))
    save.save_inventory("case-2", "ev2-index", BinlogInventory(
        "mysql-bin.index", ("mysql-bin.000005", FILE), (FILE,), ("mysql-bin.000005",),
    ))
    return case


def normalize(stores, case_id: str) -> None:
    NormalizeEvidenceUseCase(stores.cases, stores.normalizer, stores.extraction, FixedClock()
                             ).execute(case_id)


def test_normalizing_a_case_reads_only_its_own_evidence(two_cases) -> None:
    first = two_cases.normalizer.normalize("case-1")
    second = two_cases.normalizer.normalize("case-2")

    assert [(s.table, len(s.columns)) for s in first.schemas] == [("accounts", 1), ("transfers", 1)]
    assert len(first.physical_records) == 3
    assert [e.log_position for e in first.events] == [739, 985, 1112, 1300, 1500]
    assert len(first.markers) == 5

    assert [(s.table, len(s.columns)) for s in second.schemas] == [("accounts", 2)]
    assert [r.values for r in second.physical_records] == [{"account_id": 201, "iban": "LK01"}]
    assert [e.after for e in second.events] == [{"account_id": 201}]
    assert [m.start_position for m in second.markers] == [600]


def test_the_stored_totals_count_only_the_cases_own_evidence(two_cases) -> None:
    """'5 of 5 events', not '5 of 6': the other case's event is not part of this one."""
    normalize(two_cases, "case-1")

    record = SqliteNormalizationRepository(two_cases.extraction._connection).find("case-1")

    assert record.counts == {
        "schemas": (2, 2), "physical_records": (3, 3), "events": (5, 5), "markers": (5, 5),
    }


def test_the_decoder_names_columns_from_the_cases_own_schema(two_cases) -> None:
    """The newest accounts schema in the file is case-2's, but case-1's binlog
    events still have to be named with case-1's columns."""
    first = two_cases.schemas_for_case("case-1").schema_for("finance", "accounts")
    second = two_cases.schemas_for_case("case-2").schema_for("finance", "accounts")

    assert [c.name for c in first.columns_in_order()] == ["account_id"]
    assert [c.name for c in second.columns_in_order()] == ["account_id", "iban"]


def test_integrity_inventory_and_provenance_come_from_the_cases_own_files(two_cases) -> None:
    normalize(two_cases, "case-1")
    normalize(two_cases, "case-2")
    first = two_cases.domain.inputs_for("case-1").evidence
    second = two_cases.domain.inputs_for("case-2").evidence

    assert first.integrity_for("finance", "accounts").status == "damaged"
    assert second.integrity_for("finance", "accounts").status == "valid"
    assert first.inventory() is None
    assert second.inventory().missing_files == ("mysql-bin.000005",)
    assert first.provenance_for((FILE, 739)).tool_run_id == "bin"
    assert second.provenance_for((FILE, 739)).tool_run_id == "bin-2"


@pytest.mark.parametrize("case_id", ["case-1", "case-2"])
def test_each_case_is_analysed_on_its_own_evidence(two_cases, case_id) -> None:
    """Every reference in the whole analysis points into the case's own files."""
    normalize(two_cases, case_id)

    results = (
        GroupTransactionsUseCase(two_cases.domain).execute(case_id),
        CorrelateRecordsUseCase(two_cases.domain).execute(case_id),
        ReconstructStateUseCase(two_cases.domain).execute(case_id),
        ReconcileRecordsUseCase(two_cases.domain).execute(case_id),
    )

    referenced = {reference.evidence_id for reference in references_in(results)}
    assert referenced and referenced <= OWN_FILES[case_id]
    records = {r.record.id for r in results[1].records}
    assert ("accounts:201" in records) == (case_id == "case-2")
