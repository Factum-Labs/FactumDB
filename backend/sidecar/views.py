"""Read-only desktop projections, using the same tagged values as case exports."""

import json

from adapters.persistence.case_export import case_export
from sidecar.commands import _pipeline_result
from core.domain.rules import describe


def _present(value):
    if type(value) is int and abs(value) > 2**53 - 1:
        return {"__integer__": str(value)}
    if isinstance(value, list):
        return [_present(item) for item in value]
    if isinstance(value, dict):
        return {key: _present(item) for key, item in value.items()}
    return value


def _findings(value, found):
    if isinstance(value, dict):
        if "rule_id" in value and "subject" in value and "severity" in value:
            finding = dict(value)
            finding["description"] = describe(value["rule_id"], value.get("context", {}))
            found[json.dumps(finding, sort_keys=True)] = finding
        for item in value.values():
            _findings(item, found)
    elif isinstance(value, list):
        for item in value:
            _findings(item, found)


def case_view(case_id, connection, stores, pipelines):
    document = case_export(connection, case_id)
    tables = _present(document["tables"])
    run = pipelines.latest_for_case(case_id)
    results = {row["stage"]: row["result"] for row in tables["analysis_results"]}
    findings = {}
    _findings(results, findings)
    return {
        "case": tables["cases"][0],
        "tables": tables,
        "analysis": results,
        "findings": list(findings.values()),
        "run": _pipeline_result(run) if run else None,
    }
