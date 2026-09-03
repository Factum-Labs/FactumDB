"""The engine must produce byte-identical output for identical evidence.

This is a forensic requirement, not a tidiness one: a conclusion that changes
between two runs over the same evidence is not a conclusion, and an examiner who
cannot reproduce a report cannot defend it.

Three assertions, each strictly stronger than the last:

1. Running twice in one process gives identical bytes.
2. Running over *shuffled* inputs gives identical bytes. This catches dependence
   on the order the adapter happened to emit rows in - which the real pipeline
   does not guarantee.
3. Running in separate processes under different PYTHONHASHSEED values gives
   identical bytes. This catches dependence on set and dict iteration order,
   which is stable within a process and varies between them.

The frontend's `correlation.check.ts` makes assertion 1 only. Two and three are
reachable here because the domain is pure.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from core.domain.models.serialization import to_canonical_json
from tests.fixtures.datasets import ALL, DATASETS, Dataset
from tests.fixtures.pipeline import run_pipeline

BACKEND_ROOT = Path(__file__).resolve().parents[2]
IDS = [d.id for d in ALL]


def digest(dataset: Dataset) -> str:
    """The whole pipeline's output as one canonical string."""
    result = run_pipeline(dataset)
    return to_canonical_json(
        {
            "grouping": result.grouping,
            "correlation": result.correlation,
            "reconstruction": result.reconstruction,
            "reconciliation": result.reconciliation,
        }
    )


def shuffled(dataset: Dataset, seed: int) -> Dataset:
    """The same evidence, presented in a different order.

    `random` is used here in the test only - never in the domain, where the
    purity guard forbids importing it at all.
    """
    rng = random.Random(seed)
    events = list(dataset.events)
    markers = list(dataset.markers)
    physical = list(dataset.physical)
    rng.shuffle(events)
    rng.shuffle(markers)
    rng.shuffle(physical)
    return replace(
        dataset,
        events=tuple(events),
        markers=tuple(markers),
        physical=tuple(physical),
    )


def reversed_order(dataset: Dataset) -> Dataset:
    """The same evidence, back to front.

    Reversal is the permutation worth leading with: it is guaranteed to reorder
    any sequence of two or more, whereas a seeded shuffle of a two-element list
    lands on the identity half the time and would quietly test nothing.
    """
    return replace(
        dataset,
        events=tuple(reversed(dataset.events)),
        markers=tuple(reversed(dataset.markers)),
        physical=tuple(reversed(dataset.physical)),
    )


def permutations(dataset: Dataset) -> list[tuple[str, Dataset]]:
    """Every reordering this module checks the engine against."""
    return [
        ("reversed", reversed_order(dataset)),
        *((f"seed {s}", shuffled(dataset, s)) for s in (1337, 7, 99)),
    ]


def is_permutable(dataset: Dataset) -> bool:
    return max(len(dataset.events), len(dataset.markers), len(dataset.physical)) >= 2


# ── 1. Same process, same input ──────────────────────────────────────────────


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_two_runs_produce_identical_output(dataset: Dataset) -> None:
    assert digest(dataset) == digest(dataset)


# ── 2. Same process, shuffled input ──────────────────────────────────────────


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_input_order_does_not_change_the_conclusion(dataset: Dataset) -> None:
    """The adapter's emission order is not part of the evidence."""
    baseline = digest(dataset)
    for label, permuted in permutations(dataset):
        assert digest(permuted) == baseline, f"{dataset.id}: {label} changed the output"


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_shuffling_actually_reorders_something(dataset: Dataset) -> None:
    """Guard the guard: an unshufflable dataset makes the test above vacuous.

    Only a sequence with two or more entries can be permuted, so the *total*
    input count is the wrong thing to check - three single-element lists shuffle
    to themselves every time and would let the order-independence claim pass
    without ever testing it.
    """
    if not is_permutable(dataset):
        pytest.skip(f"{dataset.id} has no sequence long enough to reorder")

    reordered = any(
        permuted.events != dataset.events
        or permuted.markers != dataset.markers
        or permuted.physical != dataset.physical
        for _, permuted in permutations(dataset)
    )
    assert reordered, f"{dataset.id} was never actually permuted"


def test_the_permutable_datasets_cover_the_shapes_that_matter() -> None:
    """Most datasets are deliberately minimal, so only some can be reordered.

    That is fine as long as the ones that can include the shapes where ordering
    could plausibly leak into a conclusion: several events in one transaction,
    several transactions, and concurrent sessions. Named explicitly rather than
    counted, because a count would still pass if the wrong five qualified.
    """
    permutable = {d.id for d in ALL if is_permutable(d)}
    for required in ("ds01", "ds02", "ds03", "ds05"):
        assert required in permutable, f"{required} can no longer be reordered"


# ── 3. Separate processes, different hash seeds ──────────────────────────────


DIGEST_SCRIPT = """
import sys
sys.path.insert(0, %r)
from core.domain.models.serialization import to_canonical_json
from tests.fixtures.datasets import DATASETS
from tests.fixtures.pipeline import run_pipeline

result = run_pipeline(DATASETS[%r])
print(to_canonical_json({
    "grouping": result.grouping,
    "correlation": result.correlation,
    "reconstruction": result.reconstruction,
    "reconciliation": result.reconciliation,
}))
"""


def digest_in_subprocess(dataset_id: str, hash_seed: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", DIGEST_SCRIPT % (str(BACKEND_ROOT), dataset_id)],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
        env={"PYTHONHASHSEED": hash_seed, "PATH": ""},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.mark.parametrize("dataset_id", ["ds02", "ds05", "ds08"])
def test_hash_seed_does_not_change_the_conclusion(dataset_id: str) -> None:
    """Catches reliance on set or dict iteration order across processes.

    Three datasets rather than all twelve: each subprocess pays interpreter
    startup, and these cover the shapes with the most set-driven logic - multiple
    records, concurrent sessions, and coverage gaps.
    """
    first = digest_in_subprocess(dataset_id, "0")
    second = digest_in_subprocess(dataset_id, "1")
    assert first == second
    assert first == digest(DATASETS[dataset_id])


# ── Canonical serialization itself ───────────────────────────────────────────


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_output_is_valid_json_with_sorted_keys(dataset: Dataset) -> None:
    text = digest(dataset)
    parsed = json.loads(text)
    # `ensure_ascii=False` matches `to_canonical_json`. Escaping non-ASCII here
    # would make the comparison fail on the "·" in every record label rather
    # than on anything about key ordering.
    round_tripped = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert round_tripped == text


def test_the_dataset_registry_is_complete() -> None:
    """A shrunken registry would quietly narrow every test in this module."""
    assert len(ALL) == 12
    assert sorted(DATASETS) == [f"ds{n:02d}" for n in range(1, 13)]
