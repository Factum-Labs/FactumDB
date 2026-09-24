"""The evidence and tool run repositories - the provenance spine.

Every table holding extracted data points at a tool run, so these two are
what make "how do you know that?" answerable for any value in a report.
"""

from __future__ import annotations

import sqlite3

import pytest

from core.domain.models.evidence import (
    EvidenceKind,
    RawOutputReference,
    ToolRunStatus,
    VerificationStatus,
)
from tests.adapters.conftest import FIXED_TIME, a_binlog, a_run, an_ibd


# ── Evidence files ───────────────────────────────────────────────────────────


def test_evidence_round_trips(evidence, case_id) -> None:
    item = an_ibd(case_id)
    evidence.save(item)

    assert evidence.find_by_id("ev-ibd") == item


def test_working_copy_fields_are_null_until_the_copy_is_made(evidence, case_id) -> None:
    """A file is registered and hashed first, then copied.

    At registration there is no working copy, so a null is the honest answer.
    Requiring these fields would force a placeholder that looks like a path.
    """
    evidence.save(an_ibd(case_id))

    loaded = evidence.find_by_id("ev-ibd")

    assert loaded.working_copy_path is None
    assert loaded.working_copy_sha256 is None
    assert loaded.verification_status is VerificationStatus.REGISTERED


def test_verified_copy_is_stored_with_both_hashes(evidence, case_id) -> None:
    """Once the copy exists, both hashes are kept.

    If the source hash and the copy hash ever differ, the copy is not a
    faithful reproduction and nothing extracted from it can be relied on, so
    both have to survive independently rather than one overwriting the other.
    """
    evidence.save(
        an_ibd(
            case_id,
            working_copy_path="/cases/case-1/working/accounts.ibd",
            working_copy_sha256="a" * 64,
            verification_status=VerificationStatus.VERIFIED,
        )
    )

    loaded = evidence.find_by_id("ev-ibd")

    assert loaded.source_sha256 == loaded.working_copy_sha256
    assert loaded.verification_status is VerificationStatus.VERIFIED


def test_hash_mismatch_is_recordable(evidence, case_id) -> None:
    """A copy that does not match its source is a finding, not a crash."""
    evidence.save(
        an_ibd(
            case_id,
            working_copy_path="/cases/case-1/working/accounts.ibd",
            working_copy_sha256="f" * 64,
            verification_status=VerificationStatus.HASH_MISMATCH,
        )
    )

    loaded = evidence.find_by_id("ev-ibd")

    assert loaded.source_sha256 != loaded.working_copy_sha256
    assert loaded.verification_status is VerificationStatus.HASH_MISMATCH


def test_acquisition_method_is_stored(evidence, case_id) -> None:
    """How the file was taken is part of the evidence, not a footnote.

    FLUSH TABLES FOR EXPORT is what shows the page image is internally
    consistent rather than copied while the server was writing to it.
    """
    evidence.save(an_ibd(case_id))

    assert evidence.find_by_id("ev-ibd").acquisition_method == (
        "FLUSH TABLES FOR EXPORT + cp"
    )


def test_kind_comes_back_as_an_enum(evidence, case_id) -> None:
    """Stored as text, returned as EvidenceKind so callers compare safely."""
    evidence.save(an_ibd(case_id))

    assert evidence.find_by_id("ev-ibd").kind is EvidenceKind.IBD


def test_missing_evidence_returns_none(evidence) -> None:
    assert evidence.find_by_id("no-such-evidence") is None


def test_get_is_scoped_to_the_case(evidence, cases, case_id) -> None:
    """Scoping by case means one case cannot read another's evidence.

    find_by_id() looks up by id alone; get() requires the case to match, and
    that is the one the use cases call.
    """
    from tests.adapters.conftest import a_case

    cases.save(a_case("case-2"))
    evidence.save(an_ibd(case_id))

    assert evidence.get(case_id, "ev-ibd") is not None
    assert evidence.get("case-2", "ev-ibd") is None


def test_find_by_source_spots_a_re_registration(evidence, case_id) -> None:
    """Registering the same file twice would give it two ids and two sets of
    tool runs, so intake checks here first."""
    evidence.save(an_ibd(case_id))

    found = evidence.find_by_source(case_id, "/var/lib/mysql/finance/accounts.ibd")

    assert found.id == "ev-ibd"
    assert evidence.find_by_source(case_id, "/some/other/path") is None


def test_list_by_type_filters_and_orders(evidence, case_id) -> None:
    """The binlog stage only wants binlogs, in a stable order.

    Without an ORDER BY, SQLite may return rows in any order, and a report
    that lists evidence differently on each run looks unreliable.
    """
    evidence.save(a_binlog(case_id, "ev-b2", "mysql-bin.000002"))
    evidence.save(a_binlog(case_id, "ev-b1", "mysql-bin.000001"))
    evidence.save(an_ibd(case_id))

    binlogs = evidence.list_by_type(case_id, EvidenceKind.BINLOG)

    assert [e.filename for e in binlogs] == ["mysql-bin.000001", "mysql-bin.000002"]
    assert len(evidence.list_for_case(case_id)) == 3


def test_evidence_needs_a_real_case(evidence) -> None:
    """Foreign keys are on, so evidence cannot dangle without a case."""
    with pytest.raises(sqlite3.IntegrityError):
        evidence.save(an_ibd("no-such-case"))


# ── Tool runs ────────────────────────────────────────────────────────────────


def test_tool_run_round_trips(tool_runs, evidence, case_id) -> None:
    evidence.save(an_ibd(case_id))
    run = a_run(case_id, "ev-ibd")
    tool_runs.save(run)

    assert tool_runs.find_by_id("run-1") == run


def test_arguments_survive_as_a_list_not_a_string(tool_runs, evidence, case_id) -> None:
    """Arguments are stored as JSON rather than joined into one command line.

    Re-joining them loses the boundaries between arguments as soon as a path
    contains a space, and then nobody can tell what was actually executed.
    """
    evidence.save(an_ibd(case_id))
    tool_runs.save(
        a_run(case_id, "ev-ibd", arguments=("--sql", "/evidence/my accounts.ibd"))
    )

    loaded = tool_runs.find_by_id("run-1")

    assert loaded.arguments == ("--sql", "/evidence/my accounts.ibd")


def test_the_executable_itself_is_identified(tool_runs, evidence, case_id) -> None:
    """Hashing the binary pins the claim to one build.

    A version string can be shared by several builds; the hash cannot.
    """
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd"))

    loaded = tool_runs.find_by_id("run-1")

    assert loaded.executable_path == "/usr/bin/mysqlbinlog"
    assert loaded.executable_sha256 == "c" * 64


def test_stderr_is_captured_separately(tool_runs, evidence, case_id) -> None:
    """Both streams are kept, each with its own hash.

    innochecksum reports a damaged page on stderr, so storing only stdout
    would record an empty success for a file it had just called invalid.
    """
    evidence.save(an_ibd(case_id))
    tool_runs.save(
        a_run(
            case_id,
            "ev-ibd",
            tool_name="innochecksum",
            status=ToolRunStatus.FAILED,
            exit_code=1,
            stdout=None,
            stderr=RawOutputReference(path="/raw/run-1.err", sha256="e" * 64, size_bytes=77),
        )
    )

    loaded = tool_runs.find_by_id("run-1")

    assert loaded.stdout is None
    assert loaded.stderr.size_bytes == 77
    assert loaded.status is ToolRunStatus.FAILED


def test_a_running_tool_has_no_finish_time(tool_runs, evidence, case_id) -> None:
    """A row is written when the run starts, not only when it ends."""
    evidence.save(an_ibd(case_id))
    tool_runs.save(
        a_run(
            case_id, "ev-ibd",
            status=ToolRunStatus.RUNNING, finished_at=None, exit_code=None, stdout=None,
        )
    )

    loaded = tool_runs.find_by_id("run-1")

    assert loaded.status is ToolRunStatus.RUNNING
    assert loaded.finished_at is None
    assert loaded.exit_code is None


def test_runs_list_oldest_first(tool_runs, evidence, case_id) -> None:
    """The list reads as the order things were done in."""
    from datetime import timedelta

    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd", "run-late", started_at=FIXED_TIME + timedelta(hours=1)))
    tool_runs.save(a_run(case_id, "ev-ibd", "run-early"))

    assert [r.id for r in tool_runs.list_by_evidence("ev-ibd")] == ["run-early", "run-late"]


def test_tool_name_is_constrained(tool_runs, evidence, case_id) -> None:
    """The CHECK rejects a tool the pipeline has not been validated against."""
    evidence.save(an_ibd(case_id))
    with pytest.raises(sqlite3.IntegrityError):
        tool_runs.save(a_run(case_id, "ev-ibd", tool_name="strings"))


# ── Provenance ───────────────────────────────────────────────────────────────


def test_provenance_for_an_event(tool_runs, evidence, connection, case_id) -> None:
    """The domain layer asks "where did this event come from" and gets an answer.

    EventRef is (source_file, log_position), so the lookup joins through
    binlog_events to reach the run that produced it.
    """
    evidence.save(an_ibd(case_id))
    tool_runs.save(a_run(case_id, "ev-ibd"))
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

    provenance = tool_runs.provenance_for(("mysql-bin.000006", 1112))

    assert provenance is not None
    assert provenance.tool_run_id == "run-1"
    assert provenance.tool_name == "mysqlbinlog"
    assert provenance.evidence_id == "ev-ibd"
    assert provenance.log_position == 1112


def test_provenance_for_an_unknown_event_is_none(tool_runs) -> None:
    assert tool_runs.provenance_for(("mysql-bin.000099", 1)) is None
