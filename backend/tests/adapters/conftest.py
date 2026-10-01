"""Shared fixtures for the persistence tests.

Everything runs against an in-memory database, so the tests leave nothing
behind and finish in milliseconds. That is the reason the repositories take
an open connection rather than a file path.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_evidence_repository import SqliteEvidenceRepository
from adapters.persistence.sqlite_tool_run_repository import SqliteToolRunRepository
from core.domain.models.case import Case
from core.domain.models.evidence import (
    EvidenceFile,
    EvidenceKind,
    RawOutputReference,
    ToolRun,
    ToolRunStatus,
)

FIXED_TIME = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def connection() -> sqlite3.Connection:
    conn = open_case_database(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def cases(connection: sqlite3.Connection) -> SqliteCaseRepository:
    return SqliteCaseRepository(connection)


@pytest.fixture
def evidence(connection: sqlite3.Connection) -> SqliteEvidenceRepository:
    return SqliteEvidenceRepository(connection)


@pytest.fixture
def tool_runs(connection: sqlite3.Connection) -> SqliteToolRunRepository:
    return SqliteToolRunRepository(connection)


@pytest.fixture
def case_id(cases: SqliteCaseRepository) -> str:
    """A saved case. Evidence references one, and foreign keys are on."""
    cases.save(a_case())
    return "case-1"


def a_case(case_id: str = "case-1") -> Case:
    return Case(
        case_id,
        "finance.accounts tampering",
        "Examiner 01",
        FIXED_TIME,
        f"/cases/{case_id}",
    )


def an_ibd(case_id: str, evidence_id: str = "ev-ibd", **overrides) -> EvidenceFile:
    """An .ibd as it looks just after registration - no working copy yet."""
    fields = dict(
        id=evidence_id,
        case_id=case_id,
        source_path="/var/lib/mysql/finance/accounts.ibd",
        filename="accounts.ibd",
        kind=EvidenceKind.IBD,
        size_bytes=114688,
        source_sha256="a" * 64,
        registered_at=FIXED_TIME,
        acquisition_method="FLUSH TABLES FOR EXPORT + cp",
    )
    fields.update(overrides)
    return EvidenceFile(**fields)


def a_binlog(case_id: str, evidence_id: str, filename: str) -> EvidenceFile:
    return EvidenceFile(
        id=evidence_id,
        case_id=case_id,
        source_path=f"/var/log/mysql/{filename}",
        filename=filename,
        kind=EvidenceKind.BINLOG,
        size_bytes=2050,
        source_sha256="b" * 64,
        registered_at=FIXED_TIME,
    )


def a_run(case_id: str, evidence_id: str, run_id: str = "run-1", **overrides) -> ToolRun:
    fields = dict(
        id=run_id,
        case_id=case_id,
        evidence_id=evidence_id,
        tool_name="mysqlbinlog",
        tool_version="8.4.10",
        executable_path="/usr/bin/mysqlbinlog",
        executable_sha256="c" * 64,
        arguments=("-v", "-v", "--base64-output=DECODE-ROWS", "mysql-bin.000006"),
        started_at=FIXED_TIME,
        status=ToolRunStatus.SUCCEEDED,
        finished_at=FIXED_TIME,
        exit_code=0,
        stdout=RawOutputReference(path="/raw/run-1.out", sha256="d" * 64, size_bytes=10278),
    )
    fields.update(overrides)
    return ToolRun(**fields)
