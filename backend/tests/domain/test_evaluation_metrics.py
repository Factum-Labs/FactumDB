"""The accuracy metrics the project has to report, computed from the datasets.

Each dataset carries an `Expected` block written by hand from the evidence,
independently of the implementation. That independence is the point: a metric
derived from the engine's own output would measure nothing.

The metrics are the ones the work plan names - transaction boundary accuracy,
record correlation accuracy, reconciliation accuracy, and false positive and
negative counts. The false-positive count is the one that matters most: a false
positive here means the engine called something a conflict when the evidence
could not support it, which is the failure mode this tool exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.domain.models.classification import ReconResult
from tests.fixtures.datasets import ALL, Dataset
from tests.fixtures.pipeline import run_pipeline

IDS = [d.id for d in ALL]


@dataclass(frozen=True, slots=True)
class Score:
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return 1.0 if self.total == 0 else self.correct / self.total

    def __add__(self, other: Score) -> Score:
        return Score(self.correct + other.correct, self.total + other.total)


def transaction_score(dataset: Dataset) -> Score:
    result = run_pipeline(dataset)
    actual = {t.id: t.status.value for t in result.grouping.transactions}
    expected = dataset.expected.transactions
    correct = sum(1 for k, v in expected.items() if actual.get(k) == v)
    return Score(correct, len(expected))


def correlation_score(dataset: Dataset) -> Score:
    result = run_pipeline(dataset)
    actual = {r.record.id for r in result.reconciliation.records}
    expected = set(dataset.expected.records)
    return Score(len(expected & actual), len(expected))


def reconciliation_score(dataset: Dataset) -> Score:
    result = run_pipeline(dataset)
    actual = {f"{r.record_id}.{r.field}": r.result.value for r in result.reconciliation.rows}
    expected = dataset.expected.field_results
    correct = sum(1 for k, v in expected.items() if actual.get(k) == v)
    return Score(correct, len(expected))


def false_positives(dataset: Dataset) -> int:
    """Conflicts asserted where the evidence cannot support one."""
    if not dataset.expected.no_conflicts:
        return 0
    result = run_pipeline(dataset)
    return sum(1 for r in result.reconciliation.rows if r.result is ReconResult.CONFLICTING)


def false_negatives(dataset: Dataset) -> int:
    """Conflicts the evidence does support, reported as something weaker."""
    result = run_pipeline(dataset)
    actual = {f"{r.record_id}.{r.field}": r.result.value for r in result.reconciliation.rows}
    return sum(
        1
        for key, expected in dataset.expected.field_results.items()
        if expected == ReconResult.CONFLICTING.value and actual.get(key) != expected
    )


# ── Per-dataset ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_transaction_boundaries_are_exact(dataset: Dataset) -> None:
    score = transaction_score(dataset)
    assert score.accuracy == 1.0, f"{dataset.id}: {score.correct}/{score.total}"


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_record_correlation_is_exact(dataset: Dataset) -> None:
    score = correlation_score(dataset)
    assert score.accuracy == 1.0, f"{dataset.id}: {score.correct}/{score.total}"


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_reconciliation_classifications_are_exact(dataset: Dataset) -> None:
    score = reconciliation_score(dataset)
    assert score.accuracy == 1.0, f"{dataset.id}: {score.correct}/{score.total}"


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_no_false_positives(dataset: Dataset) -> None:
    """The failure mode that would discredit a report: a gap reported as tampering."""
    assert false_positives(dataset) == 0, f"{dataset.id} asserted an unsupportable conflict"


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_no_false_negatives(dataset: Dataset) -> None:
    """The mirror failure: refusing to report a conflict the evidence does support."""
    assert false_negatives(dataset) == 0, f"{dataset.id} understated a real conflict"


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_expected_rules_actually_fire(dataset: Dataset) -> None:
    """The reasoning has to match too, not just the verdict.

    Two engines can reach the same classification for different reasons, and only
    one of them is reproducible. This checks the cited rules.
    """
    fired = set(run_pipeline(dataset).cited_rules)
    missing = sorted(set(dataset.expected.rules) - fired)
    assert not missing, f"{dataset.id} did not cite {missing}"


# ── Aggregate, reported for the evaluation write-up ───────────────────────────


def test_evaluation_table(capsys: pytest.CaptureFixture[str]) -> None:
    """Computes the week 7 evaluation table and prints it with -s."""
    totals = {
        "transaction boundary": Score(0, 0),
        "record correlation": Score(0, 0),
        "reconciliation": Score(0, 0),
    }
    positives = negatives = 0

    lines = [
        "",
        f"{'dataset':<8} {'title':<48} {'tx':>6} {'rec':>6} {'recon':>7}",
        "-" * 80,
    ]
    for dataset in ALL:
        tx = transaction_score(dataset)
        rec = correlation_score(dataset)
        recon = reconciliation_score(dataset)
        totals["transaction boundary"] += tx
        totals["record correlation"] += rec
        totals["reconciliation"] += recon
        positives += false_positives(dataset)
        negatives += false_negatives(dataset)
        lines.append(
            f"{dataset.id:<8} {dataset.title[:48]:<48} "
            f"{tx.accuracy:>6.2f} {rec.accuracy:>6.2f} {recon.accuracy:>7.2f}"
        )

    lines.append("-" * 80)
    for name, score in totals.items():
        lines.append(f"{name:<24} {score.correct}/{score.total} = {score.accuracy:.3f}")
    lines.append(f"{'false positives':<24} {positives}")
    lines.append(f"{'false negatives':<24} {negatives}")
    print("\n".join(lines))

    assert all(score.accuracy == 1.0 for score in totals.values())
    assert positives == 0 and negatives == 0


def test_every_dataset_states_what_it_expects() -> None:
    """A dataset with no expectations would inflate every accuracy above."""
    for dataset in ALL:
        assert dataset.expected.transactions, f"{dataset.id} expects no transactions"
        assert dataset.expected.records, f"{dataset.id} expects no records"
        assert dataset.expected.field_results, f"{dataset.id} expects no field results"
        assert dataset.why, f"{dataset.id} does not say why it exists"
