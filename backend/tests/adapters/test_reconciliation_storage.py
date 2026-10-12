"""Internal compaction must preserve every external reconciliation representation."""
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from adapters.persistence._reconciliation import (
    decode_reconciliation,
    encode_reconciliation,
    expand_reconciliation,
)
from adapters.persistence._results import encode
from adapters.persistence.case_export import case_export, write_json
from core.domain.models.values import UNOBSERVED, UndecodableValue
from tests.application.auth_support import authenticated_runtime as DesktopRuntime
from tests.application.test_desktop_runtime import call, create
from tests.fixtures.datasets import ALL, DS02
from tests.fixtures.pipeline import run_pipeline


@pytest.mark.parametrize("dataset", ALL, ids=lambda d: d.id)
def test_storage_roundtrip_and_archival_equivalence(dataset):
    result = run_pipeline(dataset).reconciliation
    stored = encode_reconciliation(result)
    loaded = decode_reconciliation(json.loads(json.dumps(stored)))
    assert loaded == result
    assert encode(loaded) == encode(result)
    assert expand_reconciliation(stored) == encode(result)
    assert decode_reconciliation(encode(result)) == result
    for record in loaded.records:
        for field in record.fields:
            assert any(field is row for row in loaded.rows)
    assert encode_reconciliation(result) == stored


def test_duplicate_references_and_independent_equal_findings():
    result = run_pipeline(DS02).reconciliation
    finding = result.rows[0].findings[0]
    independent = replace(finding)
    row = replace(result.rows[0], findings=(finding, finding, independent))
    record = replace(result.records[0], fields=(row, row), findings=(finding,))
    result = replace(result, rows=(row,), records=(record,), findings=(independent, finding))
    stored = encode_reconciliation(result)
    assert len(stored["finding_pool"]) == 2
    loaded = decode_reconciliation(stored)
    assert loaded == result
    assert loaded.records[0].fields[0] is loaded.rows[0]
    assert loaded.records[0].fields[1] is loaded.rows[0]
    assert loaded.rows[0].findings[0] is loaded.rows[0].findings[1]
    assert loaded.findings[0] is loaded.rows[0].findings[2]


@pytest.mark.parametrize("bad", [-1, 999999, True, "0", None, 0.0])
@pytest.mark.parametrize("location", ["field_refs", "row_findings", "finding_refs"])
def test_invalid_references_fail(bad, location):
    data = encode_reconciliation(run_pipeline(DS02).reconciliation)
    if location == "field_refs":
        data["records"][0]["field_refs"] = [bad]
    elif location == "row_findings":
        data["rows"][0]["finding_refs"] = [bad]
    else:
        data["finding_refs"] = [bad]
    with pytest.raises(ValueError, match="invalid reference"):
        decode_reconciliation(data)


@pytest.mark.parametrize("property_name", [
    "coverage", "rows", "records", "finding_pool", "finding_refs",
])
def test_missing_properties_fail(property_name):
    data = encode_reconciliation(run_pipeline(DS02).reconciliation)
    del data[property_name]
    with pytest.raises(ValueError, match="missing required property"):
        decode_reconciliation(data)


@pytest.mark.parametrize("version", [2, None, True, "1"])
def test_unknown_versions_fail(version):
    data = encode_reconciliation(run_pipeline(DS02).reconciliation)
    data["storage_version"] = version
    with pytest.raises(ValueError, match="unsupported reconciliation storage"):
        decode_reconciliation(data)


def test_empty_results():
    result = replace(run_pipeline(DS02).reconciliation, records=(), rows=(), findings=())
    assert decode_reconciliation(encode_reconciliation(result)) == result


@pytest.mark.parametrize("value", [
    Decimal("500.0010"), datetime(2026, 10, 12, tzinfo=UTC), None,
    UNOBSERVED, UndecodableValue("invalid bytes"), True, 2**60, "00100",
])
def test_tagged_values_retain_types(value):
    result = run_pipeline(DS02).reconciliation
    row = replace(result.rows[0], log=value, phys=value)
    record = replace(result.records[0], fields=(row,))
    result = replace(result, rows=(row,), records=(record,))
    stored = encode_reconciliation(result)
    loaded = decode_reconciliation(json.loads(json.dumps(stored)))
    assert loaded == result
    assert type(loaded.rows[0].log) is type(value)
    assert expand_reconciliation(stored) == encode(result)


@pytest.mark.parametrize("location", ["row", "record", "finding", "coverage"])
def test_missing_nested_properties_fail(location):
    stored = encode_reconciliation(run_pipeline(DS02).reconciliation)
    if location == "row":
        del stored["rows"][0]["log"]
    elif location == "record":
        del stored["records"][0]["rollup"]
    elif location == "finding":
        del stored["finding_pool"][0]["context"]
    else:
        stored["coverage"] = {}
    with pytest.raises(ValueError, match="missing required property"):
        decode_reconciliation(stored)


def test_legacy_and_compact_desktop_and_exports_match(tmp_path):
    runtime = DesktopRuntime(tmp_path / "workspace")
    try:
        case_id = create(runtime)
        other_id = create(runtime, "Legacy")
        connection, stores, _ = runtime.session(case_id)
        stores.cases.save(replace(stores.cases.get(case_id), id=other_id, name="Legacy"))
        result = run_pipeline(DS02)
        for identity in (case_id, other_id):
            for stage in ("grouping", "correlation", "reconstruction", "reconciliation"):
                getattr(stores.domain, "save_" + stage)(identity, getattr(result, stage))
        compact = connection.execute("SELECT result_json FROM analysis_results WHERE case_id=? "
                                     "AND stage='reconciliation'", (case_id,)).fetchone()[0]
        legacy = json.dumps(encode(result.reconciliation))
        snapshots = []
        json_payloads = []
        for payload in (compact, legacy):
            with connection:
                connection.execute("UPDATE analysis_results SET result_json=? WHERE case_id=? "
                                   "AND stage='reconciliation'", (payload, case_id))
                connection.execute("UPDATE analysis_results SET result_json=? WHERE case_id=? "
                                   "AND stage='reconciliation'", (legacy, other_id))
            row = result.reconciliation.rows[-1]
            snapshots.append(copy.deepcopy((
                call(runtime, "get_case_data", case_id=case_id),
                call(runtime, "get_case_preview", case_id=case_id),
                call(runtime, "get_analysis_detail", case_id=case_id, kind="comparison",
                     identity=row.record_id, field=row.field),
                case_export(connection, case_id)["tables"],
            )))
            assert stores.domain.load_reconciliation(other_id) == result.reconciliation
        assert snapshots[0] == snapshots[1]
        # Saving exports adds report history; compare desktop snapshots before either save.
        for index, payload in enumerate((compact, legacy)):
            with connection:
                connection.execute("UPDATE analysis_results SET result_json=? WHERE case_id=? "
                                   "AND stage='reconciliation'", (payload, case_id))
            path = tmp_path / f"export-{index}.json"
            write_json(connection, case_id, path, profile="full",
                       now=lambda: datetime(2026, 10, 12, tzinfo=UTC))
            json_payloads.append(path.read_bytes())
        assert json_payloads[0] == json_payloads[1]
        before = connection.execute("SELECT result_json FROM analysis_results WHERE case_id=? "
                                    "AND stage='reconciliation'", (case_id,)).fetchone()[0]
        invalid = replace(result.reconciliation, rows=())
        with pytest.raises(ValueError, match="record field is missing"):
            stores.domain.save_reconciliation(case_id, invalid)
        assert connection.execute("SELECT result_json FROM analysis_results WHERE case_id=? "
                                  "AND stage='reconciliation'", (case_id,)).fetchone()[0] == before
    finally:
        runtime.close()
