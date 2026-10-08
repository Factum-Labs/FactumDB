"""The expected results of the test datasets hold together.

datasets/*/expected.json is written by hand, so a typo there would later look
like a fault in FactumDB. These checks need no evidence files: they only make
sure each file is complete and agrees with itself.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DATASETS = Path(__file__).resolve().parents[3] / "datasets"
EXPECTED = sorted(DATASETS.glob("*/expected.json"))
VERDICTS = {"Exact", "Strong", "Partial", "Conflicting", "Unresolved", "Unsupported"}


def test_every_scenario_has_its_files() -> None:
    folders = [p for p in DATASETS.glob("scenario*") if p.is_dir()]
    assert folders
    for folder in folders:
        assert {"README.md", "generate.sql", "expected.json"} <= {p.name for p in folder.iterdir()}


@pytest.mark.parametrize("path", EXPECTED, ids=[p.parent.name for p in EXPECTED])
def test_expected_results_agree_with_themselves(path) -> None:
    expected = json.loads(path.read_text())

    assert expected["scenario"] == path.parent.name
    assert all(re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) for f in expected["evidence"])
    for table, rows in expected["page_rows"].items():
        width = len(expected["columns"][table])
        assert all(len(row) == width for row in rows["live"] + rows["deleted"]), table
    for record_id, record in expected["records"].items():
        table = record_id.split(":")[0]
        (columns,) = [c for t, c in expected["columns"].items() if t.split(".")[1] == table]
        assert list(record["fields"]) == ["record presence", *columns], record_id
        allowed = [record["rollup"], *record["fields"].values()]
        assert all(verdicts and set(verdicts) <= VERDICTS for verdicts in allowed), record_id
        if "may_be_merged_into" in record:
            assert record["may_be_merged_into"] in expected["records"], record_id
