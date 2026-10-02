"""The domain repository: the services' view of a case, and their results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass

import pytest

from adapters.persistence._results import encode
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_domain_repository import STAGES
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from core.application.errors import PrerequisiteError
from core.application.models import DecodedBinlog, EvidenceScope, NormalizedEvidence
from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase,
    GroupTransactionsUseCase,
    ReconcileRecordsUseCase,
    ReconstructStateUseCase,
)
from core.application.use_cases.extraction import NormalizeEvidenceUseCase
from core.domain.models.serialization import to_canonical_json
from tests.adapters.conftest import FIXED_TIME, a_binlog, a_case, a_run
from tests.adapters.test_sqlite_binlog_events import an_event
from tests.adapters.test_sqlite_normalization import ACCOUNTS, case  # noqa: F401 - fixture
from tests.application.fakes import FixedClock
from tests.fixtures.datasets import ALL
from tests.fixtures.pipeline import run_pipeline


@pytest.fixture
def stores():
    connection = open_case_database(":memory:")
    built = build_sqlite_application_stores(connection, now=lambda: FIXED_TIME)
    built.cases.save(a_case())
    yield built
    connection.close()


def assert_same_types(original, loaded, path="result") -> None:
    """Walk both objects together and compare the type of every value.

    Equality alone is not enough: the domain's enums are StrEnums, and
    TransactionStatus.COMMITTED == "committed" is True. A result whose enums
    came back as plain strings would compare equal and still break any code
    that checks `status is TransactionStatus.COMMITTED`.
    """
    if isinstance(original, Mapping):
        assert isinstance(loaded, Mapping), path
        for key in original:
            assert_same_types(original[key], loaded[key], f"{path}[{key!r}]")
        return
    assert type(loaded) is type(original), f"{path}: {type(original)} became {type(loaded)}"
    if is_dataclass(original):
        for f in fields(original):
            assert_same_types(getattr(original, f.name), getattr(loaded, f.name),
                              f"{path}.{f.name}")
    elif isinstance(original, (tuple, list)):
        for i, (a, b) in enumerate(zip(original, loaded)):
            assert_same_types(a, b, f"{path}[{i}]")


def save_all(domain, result) -> None:
    for stage in STAGES:
        getattr(domain, f"save_{stage}")("case-1", getattr(result, stage))


def load(domain, stage):
    return getattr(domain, f"load_{stage}")("case-1")


# ── Results round-trip exactly ───────────────────────────────────────────────


@pytest.mark.parametrize("dataset", ALL, ids=[d.id for d in ALL])
def test_every_golden_result_loads_back_exactly(stores, dataset) -> None:
    """Each stage reads the previous stage's result back from the database.

    If loading changed anything - a Decimal coming back as a str, an enum as
    plain text - the later stages would be working from something other than
    what the earlier ones produced. The canonical JSON is compared as well,
    because it is what the repeatability guarantee is checked against.
    """
    result = run_pipeline(dataset)
    save_all(stores.domain, result)

    for stage in STAGES:
        loaded = load(stores.domain, stage)
        assert loaded == getattr(result, stage)
        assert to_canonical_json(loaded) == to_canonical_json(getattr(result, stage))
        assert_same_types(getattr(result, stage), loaded, stage)


def test_nothing_loads_before_it_is_saved(stores) -> None:
    assert [load(stores.domain, stage) for stage in STAGES] == [None] * 4


def test_saving_a_stage_removes_the_results_built_on_it(stores) -> None:
    """A correlation made from the old grouping must not be loaded with the new one."""
    result = run_pipeline(ALL[0])
    save_all(stores.domain, result)

    stores.domain.save_grouping("case-1", result.grouping)

    assert load(stores.domain, "grouping") == result.grouping
    assert [load(stores.domain, s) for s in STAGES[1:]] == [None, None, None]


def test_normalizing_again_removes_every_result(stores) -> None:
    """The results describe the old view of the evidence, not the new one."""
    save_all(stores.domain, run_pipeline(ALL[0]))

    stores.extraction.save_normalized("case-1", NormalizedEvidence((), (), (), ()))

    assert [load(stores.domain, stage) for stage in STAGES] == [None] * 4


def test_a_type_the_codec_does_not_know_is_refused() -> None:
    with pytest.raises(TypeError):
        encode({"finding": object()})


# ── The services' view of the case ───────────────────────────────────────────


def test_analysis_needs_normalized_evidence(case) -> None:
    with pytest.raises(PrerequisiteError, match="normalized"):
        case.domain.inputs_for("case-1")


def test_the_services_see_only_the_normalized_scope(case) -> None:
    case.scopes.save("case-1", EvidenceScope(tables=frozenset({ACCOUNTS})))
    case.extraction.save_normalized("case-1", case.normalizer.normalize("case-1"))

    inputs = case.domain.inputs_for("case-1")

    assert [e.log_position for e in inputs.events.events()] == [739, 1300]
    assert [m.start_position for m in inputs.events.markers()] == [600, 1250, 1400]
    assert inputs.schemas.tables() == [ACCOUNTS]
    assert inputs.physical.records_for("finance", "transfers") == ()
    assert inputs.evidence.tables_with_physical_evidence() == frozenset({ACCOUNTS})


def test_evidence_that_changed_after_normalizing_is_refused(case) -> None:
    """Another binlog decoded afterwards: the counts no longer match."""
    case.extraction.save_normalized("case-1", case.normalizer.normalize("case-1"))
    case.evidence.save(a_binlog("case-1", "ev-bin7", "mysql-bin.000007"))
    case.tool_runs.save(a_run("case-1", "ev-bin7", "bin7", tool_name="mysqlbinlog"))
    case.extraction.save_decoded_binlog("case-1", "ev-bin7", "bin7", DecodedBinlog(
        (an_event(104, position=200, source_file="mysql-bin.000007"),), (),
    ))

    with pytest.raises(PrerequisiteError, match="normalize it again"):
        case.domain.inputs_for("case-1")


# ── The whole analysis, on SQLite ────────────────────────────────────────────


def test_the_whole_analysis_runs_on_the_case_database(case) -> None:
    """Normalize, then all four domain stages through the application's own
    use cases, each reading the previous one's result back from SQLite."""
    NormalizeEvidenceUseCase(case.cases, case.normalizer, case.extraction, FixedClock()
                             ).execute("case-1")

    grouping = GroupTransactionsUseCase(case.domain).execute("case-1")
    CorrelateRecordsUseCase(case.domain).execute("case-1")
    ReconstructStateUseCase(case.domain).execute("case-1")
    reconciliation = ReconcileRecordsUseCase(case.domain).execute("case-1")

    assert len(grouping.transactions) == 5
    assert case.domain.load_reconciliation("case-1") == reconciliation
    assert reconciliation.rows
