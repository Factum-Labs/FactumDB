"""Run generated subjects through the actual desktop backend and external tools.

Creates disposable case workspaces under .validation-cases (gitignored).
Writes APP_VALIDATION.json and APP_VALIDATION.md beside each subject.
Usage: py -3.11 datasets/attack_lab/verify_app.py --mysql-bin ".../bin" --ibd2sql ".../main.py"
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "backend"))
from sidecar.desktop import DesktopRuntime
from sidecar.protocol import SidecarRequest, _json_default
from generate import SUBJECTS
from core.engine import ENGINE_REVISION


def pipeline_seconds(stages):
    def timestamp(value):
        return value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    return round(sum((timestamp(a['finished_at']) - timestamp(a['started_at'])).total_seconds()
                     for stage in stages for a in stage['attempts'] if a['finished_at']), 2)


def acceptance(subject, view):
    """Assert individual keys and fields, never nested occurrence counts."""
    _, _, _, people, headers, lines, ledger, staff = next(s for s in SUBJECTS if s[0] == subject)
    analysis = view['analysis']
    reconciliation = analysis['reconciliation']
    by_id = {r['record']['id']: r for r in reconciliation['records']}
    histories = {h['record']['id']: h for h in analysis['reconstruction']['histories']}
    rules = {f['rule_id'] for f in view['findings']}
    checks = {}

    def all_fields(table, keys, field, result):
        return all(any(f['field'] == field and f['result'] == result
                       for f in by_id.get(f'{table}:{key}', {}).get('fields', [])) for key in keys)

    grouped = analysis['grouping']
    retained = sum(len(t['events']) for t in grouped['transactions']) + len(grouped['ungrouped_events'])
    checks['all_decoded_rows_accounted_for'] = retained == len(view['tables']['binlog_events'])
    checks['no_false_duplicate_rows'] = 'R-GRP-013' not in rules
    if subject.startswith('06'):
        checks['15500_live_records_exact'] = len(by_id) == 15500 and all(r['rollup'] == 'Exact' for r in by_id.values())
        checks['no_unexpected_warnings'] = not any(f['severity'] in ('warning', 'error', 'notice') for f in view['findings']) and not view['tables']['warnings']
    else:
        checks['keyless_table_visible'] = 'R-CORR-020' in rules
        checks['unsupported_type_limitations_visible'] = 'R-RECON-008' in rules
        if not subject.startswith('02'):
            checks['composite_key_continuity'] = 'R-CORR-010' in rules
            checks['key_reuse'] = any(f['rule_id'] == 'R-CORR-012' and f.get('subject', {}).get('id') == f'{headers}:50' for f in view['findings'])
        # Withheld log 000002 contains these updates, so the credit union cannot observe them.
        if not subject.startswith('02'):
            checks['minimal_updates_retained'] = all(
                len(next(r for r in analysis['correlation']['records'] if r['record']['id'] == f'{headers}:{key}')['log_event_refs']) >= 2
                and not any(f['result'] == 'Conflicting' for f in by_id[f'{headers}:{key}']['fields'])
                for key in range(301, 311)
            )
        if subject.startswith('01'):
            checks['financial_rewrites_11_20'] = all_fields(headers, range(11, 21), 'amount_minor', 'Conflicting')
            checks['contact_takeovers_31_40'] = all_fields(people, range(31, 41), 'email', 'Conflicting')
            checks['role_rewrites_8_9'] = all_fields(staff, (8, 9), 'role', 'Conflicting')
            checks['hidden_deletions_81_90'] = all_fields(ledger, range(81, 91), 'record presence', 'Conflicting')
            checks['fabricated_row_900001'] = all_fields(headers, (900001,), 'record presence', 'Conflicting')
            checks['discontinuity_71'] = histories[f'{headers}:71']['before_image_mismatch']
        elif subject.startswith('02'):
            checks['withheld_key_change_not_invented'] = 'R-CORR-010' not in rules
            checks['withheld_key_reuse_not_invented'] = 'R-CORR-012' not in rules
            checks['missing_log_named'] = any('mysql-bin.000002' in g['missing_files'] for g in grouped['coverage']['gaps'])
            checks['gap_explains_financial_differences'] = all_fields(headers, range(11, 21), 'amount_minor', 'Unresolved')
            checks['fabricated_row_conservative'] = all_fields(headers, (900001,), 'record presence', 'Unresolved')
        elif subject.startswith('03'):
            checks['truncation_keeps_earlier_differences_unresolved'] = all_fields(headers, range(11, 21), 'amount_minor', 'Unresolved')
            checks['final_transaction_incomplete'] = grouped['transactions'][-1]['status'] == 'incomplete'
            checks['unterminated_changes_not_applied'] = all(
                histories[f'{headers}:{key}']['final_log_state']['values']['status'] != 'held'
                for key in range(81, 86)
            ) and histories[f'{staff}:25']['final_log_state']['values']['role'] != 'administrator'
            checks['truncated_coverage_visible'] = 'R-COV-003' in rules and 'R-GRP-004' in rules
            checks['cleanup_not_observed_rollback'] = all(t['status'] != 'rolled_back' for t in grouped['transactions'])
        elif subject.startswith('04'):
            checks['damaged_tablespace_visible'] = any(r['status'] == 'damaged' for r in view['tables']['integrity_results'])
            damaged_rows = [r for r in by_id.values() if r['record']['table'].split('.')[-1] == ledger]
            checks['damaged_presence_conservative'] = bool(damaged_rows) and all(f['result'] == 'Unresolved' for r in damaged_rows for f in r['fields'] if f['field'] == 'record presence')
            checks['damaged_values_conservative'] = bool(damaged_rows) and all(f['result'] in ('Unresolved', 'Unsupported') for r in damaged_rows for f in r['fields'])
        elif subject.startswith('05'):
            checks['missing_index_visible'] = 'R-COV-001' in rules
            checks['unavailable_invoice_schema_visible'] = any(w['code'] == 'SCHEMA_NOT_FOUND' and w['context'].get('table') == ledger for w in view['tables']['warnings'])
            checks['no_invoice_physical_values_invented'] = not any(r['table_name'] == ledger for r in view['tables']['physical_records'])
    return checks


def call(runtime, command, **payload):
    response = runtime.router().dispatch(SidecarRequest("fixture-validation", command, payload))
    if not response.ok:
        raise RuntimeError(response.to_json())
    return response.result


def collect(value, field, counts):
    if isinstance(value, dict):
        if field in value and isinstance(value[field], str):
            counts[value[field]] += 1
        for item in value.values():
            collect(item, field, counts)
    elif isinstance(value, list):
        for item in value:
            collect(item, field, counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-bin", type=Path, required=True)
    parser.add_argument("--ibd2sql", type=Path, required=True)
    parser.add_argument("--subjects", type=Path, default=ROOT / "subjects", help="Generated subjects directory")
    parser.add_argument("--subject", help="One subject folder name; by default validate all")
    parser.add_argument("--report-existing", action="store_true", help="Report the latest stored case without rerunning analysis")
    args = parser.parse_args()
    subjects = sorted(args.subjects.resolve().glob("*/manifest.json"))
    if not subjects:
        parser.error("No generated subject manifests found")
    if args.subject:
        subjects = [p for p in subjects if p.parent.name == args.subject]
        if not subjects:
            parser.error("No matching generated subject")
    failures = []
    for manifest in subjects:
        subject = manifest.parent
        print(f"Validating app: {subject.name}", flush=True)
        runtime = DesktopRuntime(ROOT / ".validation-cases" / subject.name)
        started = time.monotonic()
        try:
            runtime.settings.update({name + "_path": str(args.mysql_bin.resolve() / (name + ".exe"))
                                     for name in ("innochecksum", "ibd2sdi", "mysqlbinlog")})
            runtime.settings.update(ibd2sql_path=str(args.ibd2sql.resolve()), python_path=sys.executable, include_deleted=False)
            if args.report_existing:
                cases = call(runtime, "list_cases")
                if not cases:
                    raise RuntimeError("No previous validation case")
                case_id = cases[0]["id"]
            else:
                case_id = call(runtime, "create_case", case_name=subject.name, examiner="Synthetic fixture validation")["case_id"]
                for directory in (subject / "ibd", subject / "binlog"):
                    for path in sorted(directory.iterdir()):
                        call(runtime, "register_evidence", case_id=case_id, source_path=str(path.resolve()))
                run = call(runtime, "start_pipeline", case_id=case_id)
                while not run["stopped"]:
                    run = call(runtime, "run_next_stage", run_id=run["run_id"])
                    stage = next((s for s in reversed(run["stages"]) if s["status"] != "pending"), {})
                    print(f"  {stage.get('stage', '')}: {stage.get('status', '')}", flush=True)
            view = call(runtime, "get_case_data", case_id=case_id)
            run = view["run"]
            if not run['complete']:
                raise RuntimeError('Incomplete run: existing observed reports left unchanged')
            reconciliation = view['analysis']['reconciliation']
            records = Counter(r['rollup'] for r in reconciliation['records'])
            fields = Counter(r['result'] for r in reconciliation['rows'])
            checks = acceptance(subject.name, view)
            rules = Counter(f["rule_id"] for f in view["findings"])
            elapsed = round(time.monotonic()-started, 2) if not args.report_existing else None
            summary = {"complete": run["complete"], "elapsed_seconds": elapsed,
                       "pipeline_seconds": pipeline_seconds(run['stages']),
                       "include_deleted": False, "stages": run["stages"],
                       "physical_rows": len(view["tables"]["physical_records"]),
                       "engine_revision": ENGINE_REVISION,
                       "record_counts": dict(records), "field_counts": dict(fields),
                       "acceptance_checks": checks, "acceptance_passed": all(checks.values()),
                       "finding_rule_counts": dict(sorted(rules.items())),
                       "note": "Distinct record rollups and field rows are counted separately. Acceptance checks use exact affected keys."}
            (subject / "APP_VALIDATION.json").write_text(json.dumps(summary, indent=2, default=_json_default)+"\n", encoding="utf-8")
            timing = f"Elapsed: {elapsed} seconds." if elapsed is not None else "Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json."
            text = f"# Actual app validation: {subject.name}\n\nPipeline complete: **{run['complete']}**. Deleted-row extraction: off. Physical rows extracted: {summary['physical_rows']:,}. {timing}\n\n"
            text += "These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.\n\n"
            text += f"Engine revision: {ENGINE_REVISION}. Acceptance passed: **{all(checks.values())}**.\n\n"
            text += "Record counts:\n\n```json\n" + json.dumps(dict(records), indent=2) + "\n```\n\nField counts:\n\n```json\n" + json.dumps(dict(fields), indent=2) + "\n```\n\n"
            text += "Acceptance assertions:\n\n" + ''.join(f"- {'PASS' if passed else 'FAIL'}: {name}\n" for name, passed in checks.items()) + "\nFinding rules:\n\n"
            text += "| Rule | Count |\n|---|---:|\n" + "".join(f"| {r} | {c} |\n" for r,c in sorted(rules.items()))
            if not run["complete"]:
                text += "\nStopped pipeline details are in `APP_VALIDATION.json`.\n"
            (subject / "APP_VALIDATION.md").write_text(text, encoding="utf-8")
            print(f"  Complete={run['complete']}; records={dict(records)}; acceptance={checks}", flush=True)
            if not all(checks.values()):
                failures.append((subject.name, [name for name, passed in checks.items() if not passed]))
        finally:
            runtime.close()
    if failures:
        raise RuntimeError(f'Dataset acceptance failed: {failures}')


if __name__ == "__main__":
    main()
