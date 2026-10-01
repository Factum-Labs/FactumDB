"""Which tool runs the extraction repository accepts as provenance."""

from __future__ import annotations

import pytest

from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from core.application.errors import ConflictError, PrerequisiteError
from core.domain.models.canonical import IntegrityResult
from core.domain.models.evidence import ToolRunStatus
from tests.adapters.conftest import a_case, a_run, an_ibd


@pytest.fixture
def stores():
    connection = open_case_database(":memory:")
    built = build_sqlite_application_stores(connection)
    built.cases.save(a_case())
    built.evidence.save(an_ibd("case-1"))
    yield built
    connection.close()


def damaged() -> IntegrityResult:
    return IntegrityResult(total_pages=0, damaged_pages=1, status="damaged")


def test_damage_is_saved_against_the_failed_innochecksum_run(stores) -> None:
    """innochecksum exits 1 when it finds damage, so that run is recorded as
    failed. If only successful runs counted, damage could never be saved."""
    stores.tool_runs.save(
        a_run("case-1", "ev-ibd", "run-check", tool_name="innochecksum",
              status=ToolRunStatus.FAILED, exit_code=1)
    )

    stores.extraction.save_integrity("case-1", "ev-ibd", "run-check", damaged())

    row = stores.extraction._connection.execute(
        "SELECT tool_run_id, status FROM integrity_results"
    ).fetchone()
    assert tuple(row) == ("run-check", "damaged")


def test_output_cannot_point_at_a_run_of_another_tool(stores) -> None:
    """Schemas claiming to come from innochecksum would be false provenance."""
    stores.tool_runs.save(a_run("case-1", "ev-ibd", "run-check", tool_name="innochecksum"))

    with pytest.raises(ConflictError, match="ibd2sdi"):
        stores.extraction.save_schemas("case-1", "ev-ibd", "run-check", ())


def test_a_run_still_in_progress_is_never_used(stores) -> None:
    """It has not produced its output yet, so nothing can come from it."""
    stores.tool_runs.save(
        a_run("case-1", "ev-ibd", "run-check", tool_name="innochecksum",
              status=ToolRunStatus.RUNNING, finished_at=None, exit_code=None, stdout=None)
    )

    with pytest.raises(PrerequisiteError):
        stores.extraction.save_integrity("case-1", "ev-ibd", "run-check", damaged())
