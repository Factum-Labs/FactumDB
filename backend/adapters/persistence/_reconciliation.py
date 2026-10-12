"""Compact internal storage; domain and archival representations stay expanded."""

from dataclasses import fields, replace

from adapters.persistence._results import decode, encode
from core.domain.models.findings import Finding
from core.domain.models.reconciliation import (
    FieldReconciliation,
    ReconciliationResult,
    RecordReconciliation,
)
from core.domain.models.transactions import CoverageReport

STORAGE_FORMAT = "factumdb-reconciliation"
STORAGE_VERSION = 1


def check_storage(marker, version):
    """Validate headers without loading the document's large arrays."""
    if marker != STORAGE_FORMAT or type(version) is not int or version != STORAGE_VERSION:
        raise ValueError(f"unsupported reconciliation storage: {marker!r} version {version!r}")


def compact(data):
    if "storage_format" not in data:
        return False
    check_storage(data["storage_format"], data.get("storage_version"))
    return True


def references(refs, pool, path):
    if not isinstance(refs, list):
        raise ValueError(f"{path}: expected an array of references")
    result = []
    for index in refs:
        if type(index) is not int or not 0 <= index < len(pool):
            raise ValueError(f"{path}: invalid reference {index!r} (pool size {len(pool)})")
        result.append(pool[index])
    return result


def _required(data, name, path):
    if not isinstance(data, dict) or name not in data:
        raise ValueError(f"{path}: missing required property {name!r}")
    return data[name]


def _attributes(obj, excluded):
    return {f.name: encode(getattr(obj, f.name)) for f in fields(obj)
            if f.init and f.name not in excluded}


def encode_reconciliation(result):
    pool, indexes = [], {}

    def intern(findings):
        refs = []
        for finding in findings:
            identity = id(finding)
            if identity not in indexes:
                indexes[identity] = len(pool)
                pool.append(encode(finding))
            refs.append(indexes[identity])
        return refs

    row_indexes = {}
    rows = []
    for index, row in enumerate(result.rows):
        row_indexes.setdefault(id(row), index)
        rows.append({**_attributes(row, {"findings"}), "finding_refs": intern(row.findings)})
    records = []
    for record in result.records:
        try:
            refs = [row_indexes[id(row)] for row in record.fields]
        except KeyError as error:
            raise ValueError("record field is missing from reconciliation rows") from error
        records.append({**_attributes(record, {"fields", "findings"}),
                        "field_refs": refs, "finding_refs": intern(record.findings)})
    finding_refs = intern(result.findings)
    return {"storage_format": STORAGE_FORMAT, "storage_version": STORAGE_VERSION,
            "coverage": encode(result.coverage), "rows": rows, "records": records,
            "finding_pool": pool, "finding_refs": finding_refs}


def expand_reconciliation(data):
    """Expand tagged JSON directly, without a domain-object encode/decode cycle."""
    if not compact(data):
        return data
    for name in ("coverage", "rows", "records", "finding_pool", "finding_refs"):
        _required(data, name, "reconciliation")
    for name in ("rows", "records", "finding_pool"):
        if not isinstance(data[name], list):
            raise ValueError(f"reconciliation.{name}: expected an array")
    pool = data["finding_pool"]
    for i, finding in enumerate(pool):
        for attribute in fields(Finding):
            if attribute.init:
                _required(finding, attribute.name, f"finding_pool[{i}]")
    for attribute in fields(CoverageReport):
        if attribute.init:
            _required(data["coverage"], attribute.name, "coverage")

    def expand_entry(entry, cls, excluded, path):
        attrs = {f.name: _required(entry, f.name, path) for f in fields(cls)
                 if f.init and f.name not in excluded}
        attrs["findings"] = references(_required(entry, "finding_refs", path), pool,
                                       path + ".finding_refs")
        return attrs

    rows = [expand_entry(row, FieldReconciliation, {"findings"}, f"rows[{i}]")
            for i, row in enumerate(data["rows"])]
    records = []
    for i, entry in enumerate(data["records"]):
        record = expand_entry(entry, RecordReconciliation, {"fields", "findings"},
                              f"records[{i}]")
        record["fields"] = references(_required(entry, "field_refs", f"records[{i}]"),
                                      rows, f"records[{i}].field_refs")
        records.append(record)
    return {"coverage": data["coverage"], "rows": rows, "records": records,
            "findings": references(data["finding_refs"], pool, "finding_refs")}


def decode_reconciliation(data):
    if not compact(data):
        return decode(data, ReconciliationResult)
    # Expansion validates all references/properties; decoding pools once retains sharing.
    expanded = expand_reconciliation(data)
    pool = [decode(finding, Finding) for finding in data["finding_pool"]]
    rows = tuple(decode({**row, "findings": []}, FieldReconciliation)
                 for row in expanded["rows"])
    rows = tuple(replace(row, findings=tuple(references(entry["finding_refs"], pool,
                                                       "row.finding_refs")))
                 for row, entry in zip(rows, data["rows"], strict=True))
    records = tuple(replace(
        decode({**record, "fields": [], "findings": []}, RecordReconciliation),
        fields=tuple(references(entry["field_refs"], rows, "record.field_refs")),
        findings=tuple(references(entry["finding_refs"], pool, "record.finding_refs")),
    ) for record, entry in zip(expanded["records"], data["records"], strict=True))
    return ReconciliationResult(records, rows, decode(data["coverage"], CoverageReport),
                                tuple(references(data["finding_refs"], pool, "finding_refs")))
