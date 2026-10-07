"""Configured desktop entry point. Owns a catalog and one database per case."""

import argparse
import json
import os
import sys
from pathlib import Path

from adapters.filesystem import (
    FilesystemCaseWorkspace, FilesystemEvidenceInspector, FilesystemRawOutputStore,
    FilesystemWorkingCopyManager, Sha256FileHasher,
)
from adapters.filesystem._paths import contained, safe_component
from adapters.persistence.case_export import write_csv, write_json
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from adapters.persistence.sqlite_pipeline_repository import SqlitePipelineRepository
from core.application.defaults import UtcClock, UuidGenerator
from core.application.errors import ConflictError, NotFoundError, PrerequisiteError
from core.application.models import CreateCaseRequest
from core.application.use_cases.audit import ToolRunAuditService
from core.application.use_cases.cases import CreateCaseUseCase
from sidecar.commands import COMMAND_FIELDS, _validate
from sidecar.composition import PipelineDependencies, build_application_services, build_tool_adapters
from sidecar.main import build_router
from sidecar.protocol import CommandRouter, SidecarRequest, serve
from sidecar.views import case_view, analysis_detail


class DesktopRuntime:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = open_case_database(self.root / "catalog.db")
        self.cases = SqliteCaseRepository(self.catalog)
        self.workspace = FilesystemCaseWorkspace(self.root / "cases")
        self.ids, self.clock = UuidGenerator(), UtcClock()
        self.hasher = Sha256FileHasher()
        self.sessions = {}
        self.settings = {
            "innochecksum_path": os.environ.get("FACTUMDB_INNOCHECKSUM_PATH", "innochecksum"),
            "ibd2sdi_path": os.environ.get("FACTUMDB_IBD2SDI_PATH", "ibd2sdi"),
            "ibd2sql_path": os.environ.get("FACTUMDB_IBD2SQL_PATH", ""),
            "mysqlbinlog_path": os.environ.get("FACTUMDB_MYSQLBINLOG_PATH", "mysqlbinlog"),
            "python_path": sys.executable,
            "include_deleted": False,
        }
        self.bundled_tools = {}
        bundle = os.environ.get("FACTUMDB_BUNDLE_ROOT")
        if bundle:
            bundle = Path(bundle).resolve()
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            for name, relative in manifest["tools"].items():
                if name not in self.settings or name == "include_deleted":
                    raise ValueError(f"Unsupported bundled tool: {name}")
                path = contained(bundle, bundle / relative)
                if not path.is_file():
                    raise ValueError(f"Bundled tool missing: {path}")
                self.bundled_tools[name] = str(path)
            self.settings.update(self.bundled_tools)
        self.defaults = dict(self.settings)
        settings_path = self.root / "settings.json"
        if settings_path.exists():
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            if "overrides" in saved:
                saved = saved["overrides"]
            elif self.bundled_tools:
                # Migrate the old full settings file: placeholders were defaults,
                # whereas explicit paths remain examiner choices.
                saved = {k: v for k, v in saved.items() if k == "include_deleted" or
                         v not in ("", "innochecksum", "ibd2sdi", "mysqlbinlog", sys.executable)}
            self.settings.update({k: v for k, v in saved.items() if k in self.settings})

    def close(self):
        for connection, *_ in self.sessions.values():
            connection.close()
        self.catalog.close()

    def session(self, case_id):
        safe_component(case_id, "case id")
        case = self.cases.get(case_id)
        if case is None:
            raise NotFoundError(f"case not found: {case_id}")
        if case_id not in self.sessions:
            workspace = contained(self.root / "cases", Path(case.workspace_path))
            connection = open_case_database(workspace / "case.db")
            stores = build_sqlite_application_stores(connection)
            if stores.cases.get(case_id) is None:
                stores.cases.save(case)
            pipelines = SqlitePipelineRepository(connection)
            self.sessions[case_id] = (connection, stores, pipelines)
        return self.sessions[case_id]

    def services(self, case_id):
        _, stores, pipelines = self.session(case_id)
        audit = ToolRunAuditService(
            stores.cases, stores.evidence, stores.tool_runs,
            FilesystemRawOutputStore(self.root / "cases"), self.hasher, self.ids, self.clock,
        )
        adapters = build_tool_adapters(stores.schemas_for_case, audit=audit, **self.settings)
        return build_application_services(
            PipelineDependencies(
                cases=stores.cases, evidence=stores.evidence,
                copies=FilesystemWorkingCopyManager(self.root / "cases"), hasher=self.hasher,
                extraction=stores.extraction, normalizer=stores.normalizer, domain=stores.domain,
                pipelines=pipelines, progress=_QuietProgress(), ids=self.ids, clock=self.clock,
            ), adapters, workspaces=self.workspace, inspector=FilesystemEvidenceInspector(),
        )

    def list_cases(self, payload):
        _validate(payload, ())
        rows = self.catalog.execute("SELECT case_id FROM cases ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            _, stores, pipelines = self.session(row["case_id"])
            case = stores.cases.get(row["case_id"])
            run = pipelines.latest_for_case(case.id)
            result.append({
                "id": case.id, "name": case.name, "examiner": case.examiner,
                "workspace": case.workspace_path, "opened": case.created_at.isoformat(),
                "files": len(stores.evidence.list_for_case(case.id)),
                "engine_revision": case.engine_revision,
                "reanalysis_required": case.reanalysis_required,
                "status": "Needs reanalysis" if case.reanalysis_required else "Analysed" if run and run.complete else (
                    "Stopped" if run and run.stopped else "Pending" if run else "Registered"
                ),
            })
        return result

    def create_case(self, payload):
        values = _validate(payload, COMMAND_FIELDS["create_case"])
        response = CreateCaseUseCase(self.cases, self.workspace, self.ids, self.clock).execute(
            CreateCaseRequest(**values),
        )
        self.session(response.case_id)
        return {"case_id": response.case_id}

    def case_data(self, payload):
        case_id = _validate(payload, ("case_id",))["case_id"]
        connection, stores, pipelines = self.session(case_id)
        return case_view(case_id, connection, stores, pipelines)

    def analysis_detail(self, payload):
        kind = payload.get("kind")
        if kind not in {"history", "transaction", "comparison"}:
            raise ValueError("Unsupported analysis detail kind")
        fields = ("case_id", "kind", "identity", "field") if kind == "comparison" else ("case_id", "kind", "identity")
        values = _validate(payload, fields)
        connection, _, _ = self.session(values["case_id"])
        return analysis_detail(connection, **values)

    def application_command(self, command, payload):
        values = _validate(payload, COMMAND_FIELDS[command])
        if "case_id" in values:
            case_id = values["case_id"]
        else:
            case_id = next((
                case["id"] for case in self.list_cases({})
                if self.session(case["id"])[2].get(values["run_id"]) is not None
            ), None)
            if case_id is None:
                raise NotFoundError(f"pipeline run not found: {values['run_id']}")
        connection, _, pipelines = self.session(case_id)
        if "run_id" in values and command != "get_pipeline_status":
            latest = pipelines.latest_for_case(case_id)
            if latest is None or latest.id != values["run_id"]:
                raise ConflictError("This run is obsolete. Start or resume the current case analysis.")
        if command in {"register_evidence", "verify_evidence"}:
            if pipelines.active_for_case(case_id) is not None:
                raise ConflictError("Finish or cancel the active pipeline before changing evidence.")
        response = build_router(self.services(case_id)).dispatch(
            SidecarRequest("desktop", command, payload),
        )
        if not response.ok:
            # Keep the existing transport error code and message intact.
            return response
        if command in {"register_evidence", "start_pipeline"}:
            with connection:
                connection.execute("DELETE FROM analysis_results WHERE case_id = ?", (case_id,))
                connection.execute("DELETE FROM normalizations WHERE case_id = ?", (case_id,))
            if command == "register_evidence":
                pipelines.invalidate_case(case_id)
        return response.result

    def save_case_notes(self, payload):
        if set(payload) != {"case_id", "notes"} or not isinstance(payload.get("notes"), str):
            raise ValueError("case notes require case_id and a notes string")
        case_id = _validate({"case_id": payload["case_id"]}, ("case_id",))["case_id"]
        connection, _, _ = self.session(case_id)
        with connection:
            connection.execute("UPDATE cases SET examiner_notes = ? WHERE case_id = ?",
                               (payload["notes"], case_id))
        return self.case_data({"case_id": case_id})

    def configure(self, payload):
        if set(payload) != set(self.settings):
            raise ValueError("settings fields do not match the supported configuration")
        for name, value in payload.items():
            if name == "include_deleted":
                if type(value) is not bool:
                    raise ValueError("include_deleted must be a boolean")
            elif not isinstance(value, str) or (name != "ibd2sql_path" and not value.strip()):
                raise ValueError(f"{name} must be a nonempty executable path")
        self.settings = dict(payload)
        path = self.root / "settings.json"
        temporary = path.with_suffix(".tmp")
        overrides = {k: v for k, v in self.settings.items() if v != self.defaults[k]}
        temporary.write_text(json.dumps({"overrides": overrides}, indent=2), encoding="utf-8")
        temporary.replace(path)
        return self.get_settings({})

    def get_settings(self, payload):
        _validate(payload, ())
        return {"workspace": str(self.root), "tools": self.settings,
                "bundled_tools": self.bundled_tools}

    def export(self, payload):
        values = _validate(payload, ("case_id", "format", "path"))
        connection, _, pipelines = self.session(values["case_id"])
        run = pipelines.latest_for_case(values["case_id"])
        if run is None or not run.complete:
            raise PrerequisiteError("Complete the analysis before exporting results.")
        if values["format"] == "JSON":
            path = write_json(connection, values["case_id"], values["path"])
        elif values["format"] == "CSV":
            write_csv(connection, values["case_id"], values["path"])
            path = Path(values["path"])
        else:
            raise ValueError("Supported export formats are JSON and CSV")
        return {"path": str(path)}

    def raw_output(self, payload):
        values = _validate(payload, ("case_id", "run_id", "stream"))
        _, stores, _ = self.session(values["case_id"])
        run = stores.tool_runs.get(values["run_id"])
        if run is None or run.case_id != values["case_id"]:
            raise NotFoundError("tool run not found in this case")
        if values["stream"] not in {"stdout", "stderr"}:
            raise ValueError("stream must be stdout or stderr")
        output = getattr(run, values["stream"])
        if output is None:
            return {"text": "", "truncated": False}
        path = contained(Path(stores.cases.get(values["case_id"]).workspace_path), Path(output.path))
        if self.hasher.sha256(str(path)) != output.sha256:
            raise ConflictError("Stored raw output no longer matches its recorded SHA-256.")
        # Display a bounded preview; the exact complete bytes remain in the workspace.
        with path.open("rb") as stream:
            raw = stream.read(256 * 1024 + 1)
        return {"text": raw[:256 * 1024].decode("utf-8", errors="replace"),
                "truncated": len(raw) > 256 * 1024, "sha256": output.sha256, "path": output.path}

    def router(self):
        router = CommandRouter()
        router.register("health", lambda payload: {
            "name": "FactumDB", "status": "ready", "protocol": 1,
            "application_configured": True, "workspace": str(self.root),
        })
        router.register("create_case", self.create_case)
        router.register("list_cases", self.list_cases)
        router.register("get_case_data", self.case_data)
        router.register("get_analysis_detail", self.analysis_detail)
        router.register("save_case_notes", self.save_case_notes)
        router.register("get_settings", self.get_settings)
        router.register("configure_settings", self.configure)
        router.register("export_case", self.export)
        router.register("read_tool_output", self.raw_output)
        for command in COMMAND_FIELDS:
            if command != "create_case":
                router.register(command, lambda payload, command=command:
                                self.application_command(command, payload))
        return router


class _QuietProgress:
    def publish(self, progress):
        # The desktop receives persisted transitions after each stage. stdout is
        # reserved exclusively for correlated JSON-lines responses.
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    runtime = DesktopRuntime(args.workspace)
    try:
        serve(sys.stdin, sys.stdout, runtime.router())
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
