"""The audited tool chain, end to end.

The adapters come from build_tool_adapters, so the wiring is the one the
application uses. Each run goes through the real audit service into the real
SQLite tables. Only the tools themselves are simulated: subprocess.run answers
each command with output in the tools' real format.
"""

from __future__ import annotations

import hashlib
import itertools
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from core.application.models import EvidenceStageRequest
from core.application.use_cases.audit import ToolRunAuditService
from core.application.use_cases.extraction import (
    DecodeBinaryLogsUseCase,
    ExtractPhysicalRowsUseCase,
    RunPageValidationUseCase,
)
from core.domain.models.evidence import EvidenceKind, RawOutputReference, VerificationStatus
from sidecar.composition import build_tool_adapters
from tests.adapters.conftest import a_case, an_ibd
from tests.adapters.test_mysqlbinlog_adapter import ACCOUNTS, TEXT
from tests.application.fakes import FixedClock

VERSIONS = {
    "innochecksum": b"innochecksum  Ver 8.4.11-0ubuntu0.26.04.1 for Linux on x86_64 ((Ubuntu))\n",
    "mysqlbinlog": b"mysqlbinlog  Ver 8.4.11-0ubuntu0.26.04.1 for Linux on x86_64 ((Ubuntu))\n",
    "main.py": b"ibd2sql v2.3-20260526\n",
}
ROWS = b"INSERT INTO `finance`.`accounts`(`account_id`) VALUES (101);\n"


def output(stdout=b"", code=0, stderr=b""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def tools(command, capture_output=True):
    """Answers like the real tools would, for a damaged accounts.ibd."""
    names = [Path(part).name for part in command]
    if names[-1] == "--version":
        return output(VERSIONS["main.py" if "main.py" in names else names[0]])
    if names[0] == "innochecksum":
        return output(code=1, stderr=b"Fail: page 4 invalid\n")
    if names[0] == "mysqlbinlog":
        return output(TEXT.encode())
    if "main.py" in names:
        return output(ROWS)
    raise AssertionError(f"unexpected command: {command}")


class _Ids:
    def __init__(self):
        self._numbers = itertools.count(1)

    def new_id(self):
        return f"run-{next(self._numbers)}"


class _Hasher:
    """Remembers which files were hashed as executables."""

    def __init__(self):
        self.paths = []

    def sha256(self, path):
        self.paths.append(path)
        return "c" * 64


class _Outputs:
    """Stands in for the raw output store, which needs a real workspace."""

    def save(self, case, tool_run_id, stream_name, content):
        return RawOutputReference(
            path=f"/raw/{tool_run_id}/{stream_name}.bin",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )


def verified(evidence_id, kind, filename):
    return an_ibd(
        "case-1", evidence_id, kind=kind, filename=filename,
        source_path=f"/seized/{filename}", source_sha256="a" * 64,
        verification_status=VerificationStatus.VERIFIED,
        working_copy_path=f"/cases/case-1/working/{filename}", working_copy_sha256="a" * 64,
    )


@pytest.fixture
def chain(tmp_path):
    connection = open_case_database(":memory:")
    stores = build_sqlite_application_stores(connection)
    stores.cases.save(a_case())
    stores.evidence.save(verified("ev-ibd", EvidenceKind.IBD, "accounts.ibd"))
    stores.evidence.save(verified("ev-bin", EvidenceKind.BINLOG, "mysql-bin.000024"))
    hasher = _Hasher()
    audit = ToolRunAuditService(
        stores.cases, stores.evidence, stores.tool_runs, _Outputs(), hasher, _Ids(), FixedClock()
    )
    main_py = str(tmp_path / "ibd2sql" / "main.py")
    catalog = SimpleNamespace(schema_for=lambda d, t: ACCOUNTS if t == "accounts" else None)
    adapters = build_tool_adapters(lambda case_id: catalog, audit=audit, ibd2sql_path=main_py)
    yield SimpleNamespace(
        stores=stores, adapters=adapters, hasher=hasher, main_py=main_py, db=connection
    )
    connection.close()


def runs_of(chain, tool_name):
    return chain.db.execute(
        "SELECT * FROM tool_runs WHERE tool_name = ? ORDER BY rowid", (tool_name,)
    ).fetchall()


@patch("subprocess.run", side_effect=tools)
def test_a_damaged_tablespace_is_saved_and_traced_to_its_runs(run, chain) -> None:
    RunPageValidationUseCase(
        chain.stores.evidence, chain.adapters.page_validator, chain.stores.extraction, FixedClock()
    ).execute(EvidenceStageRequest("case-1", "ev-ibd"))

    stored = chain.db.execute("SELECT status, tool_run_id FROM integrity_results").fetchone()
    checks = runs_of(chain, "innochecksum")

    assert stored["status"] == "damaged"
    assert [r["status"] for r in checks] == ["failed", "failed"]
    assert stored["tool_run_id"] in [r["tool_run_id"] for r in checks]
    assert {r["tool_version"] for r in checks} == {"8.4.11-0ubuntu0.26.04.1"}


@patch("subprocess.run", side_effect=tools)
def test_a_multi_row_update_is_decoded_saved_and_traced(run, chain) -> None:
    """One UPDATE changing two rows: one binlog event, one position, two rows."""
    DecodeBinaryLogsUseCase(
        chain.stores.evidence, chain.adapters.decoder_for_case("case-1"),
        chain.stores.extraction, FixedClock(),
    ).execute(EvidenceStageRequest("case-1", "ev-bin"))

    links = chain.db.execute("SELECT COUNT(*) FROM transaction_events").fetchone()[0]
    provenance = chain.stores.tool_runs.provenance_for(("mysql-bin.000024", 1600, 0))

    assert links == 2
    assert provenance.tool_name == "mysqlbinlog"
    assert runs_of(chain, "mysqlbinlog")[0]["tool_version"] == "8.4.11-0ubuntu0.26.04.1"


@patch("subprocess.run", side_effect=tools)
def test_ibd2sql_is_recorded_by_its_script_not_by_python(run, chain) -> None:
    """Hashing python3 would say nothing about which ibd2sql read the rows."""
    ExtractPhysicalRowsUseCase(
        chain.stores.evidence, chain.adapters.row_extractor, chain.stores.extraction, FixedClock()
    ).execute(EvidenceStageRequest("case-1", "ev-ibd"))

    (row_run,) = runs_of(chain, "ibd2sql")

    assert row_run["executable_path"] == chain.main_py
    assert chain.hasher.paths == [chain.main_py]
    assert row_run["arguments_json"].startswith('["/cases/case-1/working/accounts.ibd"')
    assert row_run["tool_version"] == "ibd2sql v2.3-20260526"
