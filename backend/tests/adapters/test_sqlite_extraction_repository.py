"""The extraction repository - where the pipeline's stages meet the tables.

The last test runs the application's audit service and decode use case
against the real SQLite repositories, to show the provenance chain closing
from the tool run to a stored event.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

from adapters.persistence.sqlite_extraction_repository import SqliteExtractionRepository
from adapters.persistence.sqlite_transaction_repository import SqliteTransactionRepository
from adapters.persistence.sqlite_warning_repository import SqliteWarningRepository
from core.application.errors import PrerequisiteError
from core.application.models import (
    CompleteToolRunRequest,
    DecodedBinlog,
    EvidenceStageRequest,
    NormalizedEvidence,
    StartToolRunRequest,
)
from core.application.use_cases.audit import ToolRunAuditService
from core.application.use_cases.extraction import DecodeBinaryLogsUseCase
from core.domain.models.canonical import (
    AnalysisWarning,
    Column,
    IntegrityResult,
    PhysicalRecord,
    Schema,
    TransactionMarker,
)
from core.domain.models.evidence import (
    EvidenceKind,
    RawOutputReference,
    ToolRunStatus,
    VerificationStatus,
)
from tests.adapters.conftest import FIXED_TIME, a_case, a_run, an_ibd
from tests.adapters.test_mysqlbinlog_adapter import TEXT, parse
from tests.adapters.test_sqlite_binlog_events import an_event
from tests.application.fakes import FixedClock, FixedIds

BINLOG = "mysql-bin.000024"


def a_verified_binlog(case_id: str):
    return an_ibd(
        case_id,
        "ev-bin",
        kind=EvidenceKind.BINLOG,
        source_path=f"/var/log/mysql/{BINLOG}",
        filename=BINLOG,
        source_sha256="b" * 64,
        verification_status=VerificationStatus.VERIFIED,
        working_copy_path=f"/cases/{case_id}/working/{BINLOG}",
        working_copy_sha256="b" * 64,
    )


def decoded() -> DecodedBinlog:
    """One transaction: a two-row UPDATE, plus a warning for a skipped DELETE."""
    events, markers, warnings = parse()
    return DecodedBinlog(tuple(events), tuple(markers), tuple(warnings))


def count(connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def extraction(connection) -> SqliteExtractionRepository:
    return SqliteExtractionRepository(connection)


@pytest.fixture
def binlog_with_run(evidence, tool_runs, case_id) -> str:
    evidence.save(a_verified_binlog(case_id))
    tool_runs.save(a_run(case_id, "ev-bin"))
    return "ev-bin"


# ── Saving a decoded binlog ──────────────────────────────────────────────────


def test_a_decode_is_stored_against_its_tool_run(
    extraction, binlog_with_run, case_id, connection
) -> None:
    extraction.save_decoded_binlog(case_id, binlog_with_run, decoded())

    runs = connection.execute(
        """
        SELECT tool_run_id FROM binlog_events
        UNION SELECT tool_run_id FROM transactions
        UNION SELECT tool_run_id FROM warnings
        """
    ).fetchall()

    assert [r[0] for r in runs] == ["run-1"]
    assert count(connection, "binlog_events") == 2
    assert count(connection, "warnings") == 1


def test_a_multi_row_transaction_survives_the_whole_path(
    extraction, binlog_with_run, case_id, connection
) -> None:
    """Parser output straight into storage: two rows, one event, one position."""
    extraction.save_decoded_binlog(case_id, binlog_with_run, decoded())

    marker = SqliteTransactionRepository(connection).markers()[0]

    assert marker.event_positions == (1600,)
    assert count(connection, "transaction_events") == 2


def test_a_failed_decode_leaves_nothing_behind(
    extraction, binlog_with_run, case_id, connection
) -> None:
    """The marker claims an event at 985 that was never decoded.

    The events and the warning were saved before the marker failed, and all
    of it has to be rolled back - otherwise the case holds events with no
    transaction around them and nothing says why.
    """
    broken = DecodedBinlog(
        events=(an_event(101, position=739),),
        markers=(
            TransactionMarker(
                status="committed",
                start_position=600,
                end_position=1100,
                source_file="mysql-bin.000006",
                event_positions=(739, 985),
            ),
        ),
        warnings=(AnalysisWarning("SCHEMA_NOT_FOUND", "no schema for finance.audit"),),
    )

    with pytest.raises(LookupError):
        extraction.save_decoded_binlog(case_id, binlog_with_run, broken)

    assert count(connection, "binlog_events") == 0
    assert count(connection, "transactions") == 0
    assert count(connection, "warnings") == 0


def test_warnings_are_saved_when_nothing_else_is(
    extraction, binlog_with_run, case_id, connection
) -> None:
    """A decode that skipped every event is when its warnings matter most."""
    only_warnings = DecodedBinlog(
        (), (), (AnalysisWarning("SCHEMA_NOT_FOUND", "no schema for finance.audit"),)
    )

    extraction.save_decoded_binlog(case_id, binlog_with_run, only_warnings)

    saved = SqliteWarningRepository(connection).list_by_case(case_id)
    assert [w.code for w in saved] == ["SCHEMA_NOT_FOUND"]


# ── Finding the tool run ─────────────────────────────────────────────────────


def test_no_recorded_run_means_nothing_is_saved(
    extraction, evidence, case_id, connection
) -> None:
    """Data with no run behind it would make the provenance claim false."""
    evidence.save(a_verified_binlog(case_id))

    with pytest.raises(PrerequisiteError, match="mysqlbinlog"):
        extraction.save_decoded_binlog(case_id, "ev-bin", decoded())

    assert count(connection, "binlog_events") == 0


def test_a_failed_run_is_not_used(extraction, evidence, tool_runs, case_id) -> None:
    evidence.save(a_verified_binlog(case_id))
    tool_runs.save(a_run(case_id, "ev-bin", status=ToolRunStatus.FAILED, exit_code=1))

    with pytest.raises(PrerequisiteError):
        extraction.save_decoded_binlog(case_id, "ev-bin", decoded())


def test_a_run_of_a_different_tool_is_not_used(
    extraction, evidence, tool_runs, case_id
) -> None:
    """An innochecksum run says nothing about where binlog events came from."""
    evidence.save(a_verified_binlog(case_id))
    tool_runs.save(a_run(case_id, "ev-bin", tool_name="innochecksum"))

    with pytest.raises(PrerequisiteError):
        extraction.save_decoded_binlog(case_id, "ev-bin", decoded())


def test_the_latest_successful_run_is_used(
    extraction, evidence, tool_runs, case_id, connection
) -> None:
    """Chosen by finish time, not by the order the runs were saved in."""
    evidence.save(a_verified_binlog(case_id))
    later = FIXED_TIME + timedelta(hours=1)
    tool_runs.save(a_run(case_id, "ev-bin", "run-late", started_at=later, finished_at=later))
    tool_runs.save(a_run(case_id, "ev-bin", "run-early"))

    extraction.save_decoded_binlog(case_id, "ev-bin", decoded())

    used = connection.execute("SELECT DISTINCT tool_run_id FROM binlog_events").fetchall()
    assert [r[0] for r in used] == ["run-late"]


def test_evidence_cannot_borrow_a_run_from_another_case(
    extraction, cases, binlog_with_run
) -> None:
    """ev-bin and its run belong to case-1, so case-2 has no run for it."""
    cases.save(a_case("case-2"))

    with pytest.raises(PrerequisiteError):
        extraction.save_decoded_binlog("case-2", binlog_with_run, decoded())


# ── The .ibd stages ──────────────────────────────────────────────────────────


def test_each_ibd_stage_is_stored_against_its_own_tool(
    extraction, evidence, tool_runs, case_id, connection
) -> None:
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd", "run-check", tool_name="innochecksum"))
    tool_runs.save(a_run(case_id, "ev-ibd", "run-sdi", tool_name="ibd2sdi"))
    tool_runs.save(a_run(case_id, "ev-ibd", "run-sql", tool_name="ibd2sql"))

    extraction.save_integrity(
        case_id, "ev-ibd", IntegrityResult(7, 0, "valid", {"Undo log page": 0})
    )
    extraction.save_schemas(
        case_id,
        "ev-ibd",
        [Schema("finance", "accounts", (Column("account_id", 1, "int", False, True),), 80410)],
    )
    extraction.save_physical_records(
        case_id,
        "ev-ibd",
        [PhysicalRecord("finance", "accounts", {"account_id": 101}, is_deleted=False)],
    )

    def run_in(table: str) -> str:
        return connection.execute(f"SELECT tool_run_id FROM {table}").fetchone()[0]

    assert run_in("integrity_results") == "run-check"
    assert run_in("schemas") == "run-sdi"
    assert run_in("physical_records") == "run-sql"


def test_finding_no_rows_still_needs_a_run(extraction, evidence, case_id) -> None:
    """"No deleted rows found" is only a finding if ibd2sql is known to have run."""
    evidence.save(an_ibd(case_id))

    with pytest.raises(PrerequisiteError, match="ibd2sql"):
        extraction.save_physical_records(case_id, "ev-ibd", [])


def test_save_normalized_fails_loudly(extraction, case_id) -> None:
    """Pinned until the team agrees what normalised evidence should store."""
    with pytest.raises(NotImplementedError):
        extraction.save_normalized(case_id, NormalizedEvidence((), (), (), ()))


# ── The whole chain ──────────────────────────────────────────────────────────


class _Outputs:
    """Stands in for the raw output store, which needs a real workspace."""

    def save(self, case, tool_run_id, stream_name, content) -> RawOutputReference:
        return RawOutputReference(
            path=f"/raw/{tool_run_id}/{stream_name}.bin",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )


class _Hasher:
    def sha256(self, path: str) -> str:
        return "c" * 64


class _Decoder:
    def __init__(self, result: DecodedBinlog) -> None:
        self.result = result
        self.paths: list[str] = []

    def decode(self, working_copy_path: str) -> DecodedBinlog:
        self.paths.append(working_copy_path)
        return self.result


def test_the_provenance_chain_closes_end_to_end(
    connection, cases, evidence, tool_runs, case_id
) -> None:
    """The audit service records the run, the use case saves the decode, and
    the stored event leads back to that exact run.

    The running pipeline does not call the audit service yet. This is the
    wiring it needs, shown working against the real tables.
    """
    evidence.save(a_verified_binlog(case_id))
    audit = ToolRunAuditService(
        cases, evidence, tool_runs, _Outputs(), _Hasher(), FixedIds("run-audit"), FixedClock()
    )
    run = audit.start(
        StartToolRunRequest(
            case_id, "ev-bin", "mysqlbinlog", "8.4.10", "/usr/bin/mysqlbinlog",
            ("-v", "-v", "--base64-output=DECODE-ROWS", BINLOG),
        )
    )
    audit.complete(CompleteToolRunRequest(run.id, 0, TEXT.encode(), b""))

    decoder = _Decoder(decoded())
    DecodeBinaryLogsUseCase(
        evidence, decoder, SqliteExtractionRepository(connection), FixedClock()
    ).execute(EvidenceStageRequest(case_id, "ev-bin"))

    provenance = tool_runs.provenance_for((BINLOG, 1600))

    assert decoder.paths == [f"/cases/{case_id}/working/{BINLOG}"]
    assert provenance.tool_run_id == "run-audit"
    assert provenance.tool_name == "mysqlbinlog"
    assert tool_runs.get("run-audit").stdout.size_bytes == len(TEXT.encode())
