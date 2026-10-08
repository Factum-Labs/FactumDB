"""Every finding has to link back to the evidence behind it.

The case database keeps, for every extracted row, the evidence file and the
tool run that produced it. The domain services copy a ProvenanceReference from
each event, page row and transaction marker into what they conclude, so the
references have to be on those objects when the analysis reads them. Without
them a verdict such as "Exact" cannot say which binlog event or which page row
it compared.

The case is the one from the normalization tests: two seized tablespaces and
one binlog, each extracted by its own tool run, so every reference has exactly
one right answer.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

import pytest

from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase,
    GroupTransactionsUseCase,
    ReconcileRecordsUseCase,
    ReconstructStateUseCase,
)
from core.application.use_cases.extraction import NormalizeEvidenceUseCase
from core.domain.models.canonical import ProvenanceReference
from core.domain.models.values import UNOBSERVED
from tests.adapters.test_sqlite_normalization import FILE, case  # noqa: F401 - fixture
from tests.application.fakes import FixedClock


@pytest.fixture
def inputs(case):
    """What the domain services are given to analyse."""
    NormalizeEvidenceUseCase(case.cases, case.normalizer, case.extraction, FixedClock()
                             ).execute("case-1")
    return case.domain.inputs_for("case-1")


@pytest.fixture
def analysed(case):
    """All four domain stages, run through the application's own use cases."""
    NormalizeEvidenceUseCase(case.cases, case.normalizer, case.extraction, FixedClock()
                             ).execute("case-1")
    return (
        GroupTransactionsUseCase(case.domain).execute("case-1"),
        CorrelateRecordsUseCase(case.domain).execute("case-1"),
        ReconstructStateUseCase(case.domain).execute("case-1"),
        ReconcileRecordsUseCase(case.domain).execute("case-1"),
    )


def references_in(value) -> list:
    """Every ProvenanceReference anywhere inside a result."""
    if isinstance(value, ProvenanceReference):
        return [value]
    if is_dataclass(value) and not isinstance(value, type):
        return [r for f in fields(value) for r in references_in(getattr(value, f.name))]
    if isinstance(value, dict):
        return [r for v in value.values() for r in references_in(v)]
    if isinstance(value, (tuple, list)):
        return [r for v in value for r in references_in(v)]
    return []


# ── What the analysis is given ───────────────────────────────────────────────


def test_each_event_points_to_the_run_that_decoded_it(inputs) -> None:
    events = inputs.events.events()

    assert [e.provenance for e in events] == [
        ProvenanceReference("ev-bin", "mysqlbinlog", "bin", FILE, e.log_position, e.row_index)
        for e in events
    ]


def test_each_page_row_points_to_its_own_run_and_file(inputs) -> None:
    """Two tablespaces, two ibd2sql runs: each row names the right one."""
    accounts = inputs.physical.records_for("finance", "accounts")
    transfers = inputs.physical.records_for("finance", "transfers")

    assert {r.provenance for r in accounts} == {
        ProvenanceReference("ev-ibd", "ibd2sql", "sql-a", "accounts.ibd")
    }
    assert {r.provenance for r in transfers} == {
        ProvenanceReference("ev-transfers", "ibd2sql", "sql-t", "transfers.ibd")
    }


def test_each_marker_points_to_the_run_that_saw_it(inputs) -> None:
    markers = inputs.events.markers()

    assert [m.provenance for m in markers] == [
        ProvenanceReference("ev-bin", "mysqlbinlog", "bin", FILE, m.start_position)
        for m in markers
    ]


# ── What the analysis concludes ──────────────────────────────────────────────


def test_every_reference_in_the_results_names_a_real_run_of_the_case(case, analysed) -> None:
    """A reference to a run that does not exist, or to the wrong tool or
    file, would be worse than none: it sends the examiner to the wrong
    evidence."""
    references = references_in(analysed)

    assert references
    for reference in set(references):
        run = case.tool_runs.get(reference.tool_run_id)
        assert run is not None and run.case_id == "case-1"
        assert (reference.tool_name, reference.evidence_id) == (run.tool_name, run.evidence_id)


def test_every_observed_value_in_a_verdict_links_to_its_evidence(analysed) -> None:
    """A value the log showed points to its event; a value on the page points
    to its row. A side with nothing observed has nothing to point to."""
    rows = [row for row in analysed[-1].rows if not row.is_presence]
    from_log = [row for row in rows if row.log is not UNOBSERVED]
    from_page = [row for row in rows if row.phys is not UNOBSERVED]

    assert from_log and from_page
    assert all(row.provenance.log for row in from_log)
    assert all(row.provenance.physical is not None for row in from_page)
