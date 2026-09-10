"""Golden snapshots: any change to a conclusion shows up as a reviewable diff.

The behaviour tests assert specific claims. These assert everything else - the
exact set of findings, their contexts, the provenance attached to each. A rule
change that quietly alters what the engine says about ds08 fails here even if no
targeted test covers that particular sentence.

Regenerate with `pytest --update-golden` and read the diff before committing it.
The diff is the point: a snapshot updated without being read is worse than none,
because it launders a regression into an approved baseline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.domain.models.serialization import to_readable_json
from tests.fixtures.datasets import ALL, Dataset
from tests.fixtures.pipeline import run_pipeline

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
IDS = [d.id for d in ALL]


def snapshot(dataset: Dataset) -> str:
    result = run_pipeline(dataset)
    return to_readable_json(
        {
            "id": dataset.id,
            "title": dataset.title,
            "transactions": result.grouping.transactions,
            "ungrouped_events": result.grouping.ungrouped_events,
            "coverage": result.grouping.coverage,
            "records": result.correlation.records,
            "edges": result.correlation.edges,
            "unsupported_tables": result.correlation.unsupported_tables,
            "histories": result.reconstruction.histories,
            "reconciliation": result.reconciliation.records,
            "rules_cited": result.cited_rules,
        }
    )


@pytest.mark.parametrize("dataset", ALL, ids=IDS)
def test_matches_golden(dataset: Dataset, update_golden: bool) -> None:
    path = GOLDEN_DIR / f"{dataset.id}.json"
    current = snapshot(dataset)

    if update_golden:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(current, encoding="utf-8", newline="\n")
        pytest.skip(f"rewrote {path.name}")

    assert path.exists(), f"{path.name} is missing; run pytest --update-golden"
    assert current == path.read_text(encoding="utf-8"), (
        f"{dataset.id} output changed. Review the diff, then run pytest --update-golden."
    )


def test_every_dataset_has_a_snapshot() -> None:
    """A dataset without one is silently unguarded."""
    missing = [d.id for d in ALL if not (GOLDEN_DIR / f"{d.id}.json").exists()]
    assert not missing, f"no golden snapshot for: {missing}"


def test_no_orphaned_snapshots() -> None:
    """A snapshot for a deleted dataset would sit there asserting nothing."""
    known = {f"{d.id}.json" for d in ALL}
    orphans = sorted(p.name for p in GOLDEN_DIR.glob("*.json") if p.name not in known)
    assert not orphans, f"golden snapshots with no dataset: {orphans}"
