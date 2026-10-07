"""Run generated subjects through the actual desktop backend and external tools.

Creates disposable case workspaces under .validation-cases (gitignored).
Writes APP_VALIDATION.json and APP_VALIDATION.md beside each subject.
Usage: py -3.11 datasets/attack_lab/verify_app.py --mysql-bin ".../bin" --ibd2sql ".../main.py"
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "backend"))
from sidecar.desktop import DesktopRuntime
from sidecar.protocol import SidecarRequest, _json_default


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
            classifications = Counter()
            collect(view["analysis"].get("reconciliation", {}), "result", classifications)
            rules = Counter(f["rule_id"] for f in view["findings"])
            elapsed = round(time.monotonic()-started, 2) if not args.report_existing else None
            summary = {"complete": run["complete"], "elapsed_seconds": elapsed,
                       "include_deleted": False, "stages": run["stages"],
                       "physical_rows": len(view["tables"]["physical_records"]),
                       "classification_occurrences": dict(classifications), "finding_rule_counts": dict(sorted(rules.items())),
                       "note": "Counts include nested field/record results. Actual app observations; consult EXPECTED_FINDINGS.md for acceptance criteria."}
            (subject / "APP_VALIDATION.json").write_text(json.dumps(summary, indent=2, default=_json_default)+"\n", encoding="utf-8")
            timing = f"Elapsed: {elapsed} seconds." if elapsed is not None else "Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json."
            text = f"# Actual app validation: {subject.name}\n\nPipeline complete: **{run['complete']}**. Deleted-row extraction: off. Physical rows extracted: {summary['physical_rows']:,}. {timing}\n\n"
            text += "These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.\n\n"
            text += "Classification occurrences (nested record/field results):\n\n```json\n" + json.dumps(dict(classifications), indent=2) + "\n```\n\nFinding rules:\n\n"
            text += "| Rule | Count |\n|---|---:|\n" + "".join(f"| {r} | {c} |\n" for r,c in sorted(rules.items()))
            if not run["complete"]:
                text += "\nStopped pipeline details are in `APP_VALIDATION.json`.\n"
            (subject / "APP_VALIDATION.md").write_text(text, encoding="utf-8")
            print(f"  Complete={run['complete']}; classifications={dict(classifications)}", flush=True)
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
