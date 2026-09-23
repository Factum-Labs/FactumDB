"""The evidence and tool-run repositories - the provenance spine.

Every other table that holds extracted data points at a tool run, so these two
are what make "how do you know that?" answerable for any value in a report.
"""

from __future__ import annotations

import sqlite3

import pytest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_evidence_repository import SqliteEvidenceRepository
from adapters.persistence.sqlite_tool_run_repository import SqliteToolRunRepository
from core.application.case_factory import new_case
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from core.domain.models.evidence import EvidenceFile, ToolRun


@pytest.fixture
def connection() -> sqlite3.Connection:
    conn = open_case_database(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def case_id(connection: sqlite3.Connection) -> str:
    """A saved case. Evidence rows reference one, and foreign keys are on."""
    case = new_case(case_name="finance.accounts tampering", examiner="Examiner 01")
    SqliteCaseRepository(connection).save(case)
    return case.case_id


@pytest.fixture
def evidence_repo(connection: sqlite3.Connection) -> SqliteEvidenceRepository:
    return SqliteEvidenceRepository(connection)


@pytest.fixture
def tool_run_repo(connection: sqlite3.Connection) -> SqliteToolRunRepository:
    return SqliteToolRunRepository(connection)


def an_ibd(case_id: str, evidence_id: str = "ev-ibd") -> EvidenceFile:
    return EvidenceFile(
        evidence_id=evidence_id,
        case_id=case_id,
        evidence_type="ibd",
        file_name="accounts.ibd",
        original_path="/var/lib/mysql/finance/accounts.ibd",
        size_bytes=114688,
        sha256_original="a" * 64,
        working_copy_path="/case/working/accounts.ibd",
        sha256_working="a" * 64,
        registered_at="2026-09-23T10:00:00Z",
        acquisition_method="FLUSH TABLES FOR EXPORT + cp",
    )


def a_binlog(case_id: str, evidence_id: str, name: str) -> EvidenceFile:
    return EvidenceFile(
        evidence_id=evidence_id,
        case_id=case_id,
        evidence_type="binlog",
        file_name=name,
        original_path=f"/var/log/mysql/{name}",
        size_bytes=2050,
        sha256_original="b" * 64,
        working_copy_path=f"/case/working/{name}",
        sha256_working="b" * 64,
        registered_at="2026-09-23T10:00:00Z",
    )


# ── Evidence files ───────────────────────────────────────────────────────────


def test_evidence_round_trips(evidence_repo, case_id: str) -> None:
    evidence = an_ibd(case_id)
    evidence_repo.save(evidence)

    assert evidence_repo.find_by_id("ev-ibd") == evidence


def test_acquisition_method_is_stored(evidence_repo, case_id: str) -> None:
    """How the file was taken is part of the evidence, not a footnote.

    FLUSH TABLES FOR EXPORT is what shows the page image is internally
    consistent rather than copied while the server was writing to it.
    """
    evidence_repo.save(an_ibd(case_id))

    loaded = evidence_repo.find_by_id("ev-ibd")

    assert loaded.acquisition_method == "FLUSH TABLES FOR EXPORT + cp"


def test_both_hashes_are_kept(evidence_repo, case_id: str) -> None:
    """The original and the working copy are hashed separately.

    If the two ever differ, the working copy is not a faithful reproduction
    and nothing extracted from it can be relied on, so both have to survive.
    """
    mismatched = EvidenceFile(
        evidence_id="ev-bad",
        case_id=case_id,
        evidence_type="ibd",
        file_name="accounts.ibd",
        original_path="/x/accounts.ibd",
        size_bytes=10,
        sha256_original="a" * 64,
        working_copy_path="/w/accounts.ibd",
        sha256_working="c" * 64,
        registered_at="2026-09-23T10:00:00Z",
    )
    evidence_repo.save(mismatched)

    loaded = evidence_repo.find_by_id("ev-bad")

    assert loaded.sha256_original != loaded.sha256_working


def test_missing_evidence_returns_none(evidence_repo) -> None:
    assert evidence_repo.find_by_id("no-such-evidence") is None


def test_list_by_type_filters_and_orders(evidence_repo, case_id: str) -> None:
    """The binlog stage only wants binlogs, in a stable order."""
    evidence_repo.save(a_binlog(case_id, "ev-b2", "mysql-bin.000002"))
    evidence_repo.save(a_binlog(case_id, "ev-b1", "mysql-bin.000001"))
    evidence_repo.save(an_ibd(case_id))

    binlogs = evidence_repo.list_by_type(case_id, "binlog")

    assert [e.file_name for e in binlogs] == [
        "mysql-bin.000001",
        "mysql-bin.000002",
    ]
    assert len(evidence_repo.list_by_case(case_id)) == 3


def test_evidence_needs_a_real_case(evidence_repo) -> None:
    """Foreign keys are on, so evidence cannot dangle without a case."""
    with pytest.raises(sqlite3.IntegrityError):
        evidence_repo.save(an_ibd("no-such-case"))


def test_evidence_type_is_constrained(evidence_repo, case_id: str) -> None:
    """The CHECK on evidence_type rejects anything unexpected."""
    wrong = EvidenceFile(
        evidence_id="ev-x",
        case_id=case_id,
        evidence_type="redo_log",
        file_name="x",
        original_path="/x",
        size_bytes=1,
        sha256_original="a" * 64,
        working_copy_path="/w/x",
        sha256_working="a" * 64,
        registered_at="2026-09-23T10:00:00Z",
    )
    with pytest.raises(sqlite3.IntegrityError):
        evidence_repo.save(wrong)


# ── Tool runs ────────────────────────────────────────────────────────────────


def a_run(evidence_id: str, run_id: str = "run-1", started: str = "2026-09-23T10:05:00Z") -> ToolRun:
    return ToolRun(
        tool_run_id=run_id,
        evidence_id=evidence_id,
        tool_name="mysqlbinlog",
        command="mysqlbinlog -v -v --base64-output=DECODE-ROWS mysql-bin.000006",
        started_at=started,
        tool_version="8.4.10",
        finished_at="2026-09-23T10:05:01Z",
        exit_code=0,
        raw_output_path="/case/raw/run-1.txt",
        raw_output_sha256="d" * 64,
    )


def test_tool_run_round_trips(tool_run_repo, evidence_repo, case_id: str) -> None:
    evidence_repo.save(an_ibd(case_id))
    run = a_run("ev-ibd")
    tool_run_repo.save(run)

    assert tool_run_repo.find_by_id("run-1") == run


def test_failed_run_is_recorded_not_discarded(
    tool_run_repo, evidence_repo, case_id: str
) -> None:
    """A tool that failed is still evidence about what was attempted."""
    evidence_repo.save(an_ibd(case_id))
    failed = ToolRun(
        tool_run_id="run-fail",
        evidence_id="ev-ibd",
        tool_name="innochecksum",
        command="innochecksum accounts.ibd",
        started_at="2026-09-23T10:06:00Z",
        exit_code=1,
    )
    tool_run_repo.save(failed)

    loaded = tool_run_repo.find_by_id("run-fail")

    assert loaded.exit_code == 1
    assert loaded.tool_version is None
    assert loaded.finished_at is None


def test_runs_list_oldest_first(tool_run_repo, evidence_repo, case_id: str) -> None:
    evidence_repo.save(an_ibd(case_id))
    tool_run_repo.save(a_run("ev-ibd", "run-late", "2026-09-23T11:00:00Z"))
    tool_run_repo.save(a_run("ev-ibd", "run-early", "2026-09-23T09:00:00Z"))

    runs = tool_run_repo.list_by_evidence("ev-ibd")

    assert [r.tool_run_id for r in runs] == ["run-early", "run-late"]


def test_tool_name_is_constrained(tool_run_repo, evidence_repo, case_id: str) -> None:
    evidence_repo.save(an_ibd(case_id))
    with pytest.raises(sqlite3.IntegrityError):
        tool_run_repo.save(
            ToolRun(
                tool_run_id="run-x",
                evidence_id="ev-ibd",
                tool_name="strings",
                command="strings accounts.ibd",
                started_at="2026-09-23T10:00:00Z",
            )
        )


# ── Provenance ───────────────────────────────────────────────────────────────


def test_provenance_for_an_event(
    tool_run_repo, evidence_repo, connection: sqlite3.Connection, case_id: str
) -> None:
    """The domain layer asks "where did this event come from" and gets an answer.

    EventRef is (source_file, log_position), so the lookup joins through
    binlog_events to reach the run that produced it.
    """
    evidence_repo.save(an_ibd(case_id))
    tool_run_repo.save(a_run("ev-ibd"))
    connection.execute(
        """
        INSERT INTO binlog_events (event_id, evidence_id, tool_run_id, event_type,
            database_name, table_name, before_json, after_json, event_time_utc,
            raw_timestamp, gtid, thread_id, source_file, log_position)
        VALUES ('evt-1', 'ev-ibd', 'run-1', 'DELETE', 'finance', 'accounts',
                '{}', NULL, '2026-08-15T19:06:25Z', '260816  0:36:25',
                NULL, 13, 'mysql-bin.000006', 1112)
        """
    )
    connection.commit()

    provenance = tool_run_repo.provenance_for(("mysql-bin.000006", 1112))

    assert provenance is not None
    assert provenance.tool_run_id == "run-1"
    assert provenance.tool_name == "mysqlbinlog"
    assert provenance.evidence_id == "ev-ibd"
    assert provenance.log_position == 1112


def test_provenance_for_an_unknown_event_is_none(tool_run_repo) -> None:
    assert tool_run_repo.provenance_for(("mysql-bin.000099", 1)) is None
