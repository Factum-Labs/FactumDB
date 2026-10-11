"""Configured desktop entry point. Owns a catalog and one database per case."""

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path

from adapters.filesystem import (
    FilesystemCaseWorkspace,
    FilesystemEvidenceInspector,
    FilesystemRawOutputStore,
    FilesystemWorkingCopyManager,
    Sha256FileHasher,
)
from adapters.filesystem._paths import contained, safe_component
from adapters.filesystem.workspace_backup import (
    create_backup,
    digest,
    inspect_backup,
    rebase_and_validate,
    usage,
)
from adapters.persistence.case_export import write_csv, write_json
from adapters.persistence.sqlite_accounts import SqliteAccountStore
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_database import open_case_database
from adapters.persistence.sqlite_integration import build_sqlite_application_stores
from adapters.persistence.sqlite_pipeline_repository import SqlitePipelineRepository
from adapters.security import device_security
from core.application.authentication import AuthenticationService
from core.application.defaults import UtcClock, UuidGenerator
from core.application.errors import ConflictError, NotFoundError, PrerequisiteError
from core.application.models import CreateCaseRequest
from core.application.orchestration.models import StageStatus
from core.application.preferences import DEFAULTS, validate_preferences
from core.application.use_cases.audit import ToolRunAuditService
from core.application.use_cases.cases import CreateCaseUseCase
from sidecar.commands import COMMAND_FIELDS, _validate
from sidecar.composition import (
    PipelineDependencies,
    build_application_services,
    build_tool_adapters,
)
from sidecar.main import build_router
from sidecar.native_verification import NativeVerificationBridge
from sidecar.protocol import CommandRouter, SidecarRequest, serve
from sidecar.views import analysis_detail, case_view


class DesktopRuntime:
    def __init__(self, root, *, device=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = open_case_database(self.root / "catalog.db")
        self.auth = AuthenticationService(
            SqliteAccountStore(self.catalog), device or device_security()
        )
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
                saved = {
                    k: v
                    for k, v in saved.items()
                    if k == "include_deleted"
                    or v not in ("", "innochecksum", "ibd2sdi", "mysqlbinlog", sys.executable)
                }
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
        actor = self.auth.require_actor()
        audit = ToolRunAuditService(
            stores.cases,
            stores.evidence,
            stores.tool_runs,
            FilesystemRawOutputStore(self.root / "cases"),
            self.hasher,
            self.ids,
            self.clock,
            **actor,
        )
        adapters = build_tool_adapters(stores.schemas_for_case, audit=audit, **self.settings)
        return build_application_services(
            PipelineDependencies(
                cases=stores.cases,
                evidence=stores.evidence,
                copies=FilesystemWorkingCopyManager(self.root / "cases"),
                hasher=self.hasher,
                extraction=stores.extraction,
                normalizer=stores.normalizer,
                domain=stores.domain,
                pipelines=pipelines,
                progress=_QuietProgress(),
                ids=self.ids,
                clock=self.clock,
                **actor,
            ),
            adapters,
            workspaces=self.workspace,
            inspector=FilesystemEvidenceInspector(),
        )

    def list_cases(self, payload):
        _validate(payload, ())
        rows = self.catalog.execute("SELECT case_id FROM cases ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            _, stores, pipelines = self.session(row["case_id"])
            case = stores.cases.get(row["case_id"])
            run = pipelines.latest_for_case(case.id)
            result.append(
                {
                    "id": case.id,
                    "name": case.name,
                    "examiner": case.examiner,
                    "workspace": case.workspace_path,
                    "opened": case.created_at.isoformat(),
                    "files": len(stores.evidence.list_for_case(case.id)),
                    "engine_revision": case.engine_revision,
                    "reanalysis_required": case.reanalysis_required,
                    "status": "Needs reanalysis"
                    if case.reanalysis_required
                    else "Analysed"
                    if run and run.complete
                    else ("Stopped" if run and run.stopped else "Pending" if run else "Registered"),
                }
            )
        return result

    def create_case(self, payload):
        # The authenticated account is authoritative, even if an older client
        # includes an examiner field. Never trust a caller-supplied identity.
        fields = ("case_name", "examiner") if "examiner" in payload else ("case_name",)
        values = _validate(payload, fields)
        values["examiner"] = self.auth.require_user()["username"]
        response = CreateCaseUseCase(self.cases, self.workspace, self.ids, self.clock).execute(
            CreateCaseRequest(**values),
        )
        self.session(response.case_id)
        return {"case_id": response.case_id}

    def case_data(self, payload):
        case_id = _validate(payload, ("case_id",))["case_id"]
        connection, stores, pipelines = self.session(case_id)
        return case_view(case_id, connection, stores, pipelines)

    def delete_case(self, payload):
        self.auth.require_user()
        values = _validate(payload, ("case_id", "confirmation"))
        case_id = safe_component(values["case_id"], "case id")
        case = self.cases.get(case_id)
        if case is None:
            raise NotFoundError(f"case not found: {case_id}")
        if values["confirmation"] != case.name:
            raise ValueError("Type the case name to confirm permanent deletion.")
        cases_root = self.root / "cases"
        expected = cases_root / case_id
        workspace = contained(cases_root, Path(case.workspace_path))
        if expected.is_symlink() or workspace != expected.absolute():
            raise ValueError("Case workspace does not match its designated folder.")
        connection, stores, pipelines = self.session(case_id)
        run = pipelines.latest_for_case(case_id)
        if run and any(stage.status is StageStatus.RUNNING for stage in run.stages):
            raise ConflictError("Cannot delete a case while analysis is running.")
        for evidence in stores.evidence.list_for_case(case_id):
            if Path(evidence.source_path).resolve().is_relative_to(workspace):
                raise ConflictError(
                    "Original evidence is inside the case folder; move it before deleting."
                )
        connection.close()
        del self.sessions[case_id]

        def remove_readonly(function, path, exc_info):
            target = contained(workspace, Path(path))
            if not isinstance(exc_info[1], PermissionError) or Path(path).is_symlink():
                raise exc_info[1]
            target.chmod(stat.S_IWRITE | stat.S_IREAD)
            function(path)

        # The JSON-lines server serializes commands, including analysis and exports.
        # Keep the catalog entry until filesystem removal succeeds.
        shutil.rmtree(workspace, onerror=remove_readonly)
        with self.catalog:
            self.catalog.execute("DELETE FROM cases WHERE case_id = ?", (case_id,))
        return {"deleted": True, "case_id": case_id}

    def analysis_detail(self, payload):
        kind = payload.get("kind")
        if kind not in {"history", "transaction", "comparison"}:
            raise ValueError("Unsupported analysis detail kind")
        fields = ("case_id", "kind", "identity", "field") if kind == "comparison" else ("case_id", "kind", "identity")
        if kind == "history" and "qualified_table" in payload:
            fields += ("qualified_table",)
        values = _validate(payload, fields)
        connection, _, _ = self.session(values["case_id"])
        return analysis_detail(connection, **values)

    def history_query(self, command, payload):
        from adapters.persistence.sqlite_history_summary_repository import HistorySummaries
        allowed = {"case_id"} | ({"identity", "qualified_table"} if command == "locate" else {"database", "table", "offset", "limit", "include_details"} if command == "page" else set())
        if set(payload) - allowed:
            raise ValueError("Unsupported history query fields")
        case_id = _validate({"case_id": payload.get("case_id")}, ("case_id",))["case_id"]
        connection, _, _ = self.session(case_id)
        repository = HistorySummaries(connection)
        if command == "tables":
            return repository.tables(case_id)
        if command == "locate":
            identity = _validate({"identity": payload.get("identity")}, ("identity",))["identity"]
            return repository.locate(case_id, identity, payload.get("qualified_table"))
        return repository.page(case_id, payload.get("database"), payload.get("table"), payload.get("offset", 0), payload.get("limit", 100), payload.get("include_details", False))

    def application_command(self, command, payload):
        values = _validate(payload, COMMAND_FIELDS[command])
        if "case_id" in values:
            case_id = values["case_id"]
        else:
            case_id = next(
                (
                    case["id"]
                    for case in self.list_cases({})
                    if self.session(case["id"])[2].get(values["run_id"]) is not None
                ),
                None,
            )
            if case_id is None:
                raise NotFoundError(f"pipeline run not found: {values['run_id']}")
        connection, _, pipelines = self.session(case_id)
        if "run_id" in values and command != "get_pipeline_status":
            latest = pipelines.latest_for_case(case_id)
            if latest is None or latest.id != values["run_id"]:
                raise ConflictError(
                    "This run is obsolete. Start or resume the current case analysis."
                )
        if (
            command in {"register_evidence", "verify_evidence"}
            and pipelines.active_for_case(case_id) is not None
        ):
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
            connection.execute(
                "UPDATE cases SET examiner_notes = ? WHERE case_id = ?", (payload["notes"], case_id)
            )
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
        user = self.auth.require_user()
        details = self.auth.accounts.details(user["username"].lower())
        return {
            "workspace": str(self.root),
            "tools": self.settings,
            "bundled_tools": self.bundled_tools,
            "profile": details["profile"],
            "preferences": {**DEFAULTS, **details["preferences"]},
        }

    def configure_preferences(self, payload):
        values = validate_preferences(dict(payload))
        user = self.auth.require_user()
        self.auth.accounts.save_details(user["username"].lower(), preferences=values)
        self.auth.lock_minutes = values["lock_minutes"]
        self.auth.last_activity = time.monotonic()
        return self.get_settings({})

    def configure_profile(self, payload):
        if set(payload) != {"display_name", "organization", "examiner_id"}:
            raise ValueError("Unsupported profile fields")
        if any(not isinstance(value, str) or len(value) > 200 for value in payload.values()):
            raise ValueError("Profile fields must contain at most 200 characters")
        user = self.auth.require_user()
        self.auth.accounts.save_details(
            user["username"].lower(), profile={k: v.strip() for k, v in payload.items()}
        )
        return self.get_settings({})

    def storage_usage(self, payload):
        _validate(payload, ())
        return usage(self.root)

    def backup_workspace(self, payload):
        path = _validate(payload, ("path",))["path"]
        self.ensure_storage_idle()
        return create_backup(self.root, path)

    def inspect_workspace_backup(self, payload):
        path = _validate(payload, ("path",))["path"]
        checksum = digest(path)
        manifest = inspect_backup(path)
        if digest(path) != checksum:
            raise ConflictError("Backup changed while it was being verified. Select it again.")
        return {
            "created_at": manifest["created_at"],
            "case_count": manifest["case_count"],
            "total_bytes": manifest["total_bytes"],
            "sha256": checksum,
            "original_evidence_included": False,
        }

    def ensure_storage_idle(self):
        for row in self.catalog.execute("SELECT case_id FROM cases"):
            _, _, pipelines = self.session(row[0])
            run = pipelines.latest_for_case(row[0])
            if run and any(stage.status.value == "running" for stage in run.stages):
                raise ConflictError(
                    "Finish the running analysis stage before backing up or restoring"
                )

    def restore_workspace(self, payload):
        values = _validate(payload, ("path", "sha256", "current_password"))
        self.auth.verify_password(values["current_password"])
        self.ensure_storage_idle()
        if digest(values["path"]) != values["sha256"]:
            raise ConflictError("Backup changed after preview. Select it again.")
        device = self.auth.device
        session_user = self.auth.user
        session_lock_minutes = self.auth.lock_minutes
        root = self.root
        rollback = root.with_name(root.name + ".rollback-" + uuid.uuid4().hex[:12])
        with tempfile.TemporaryDirectory(prefix=".factumdb-restore-", dir=root.parent) as temporary:
            staging = Path(temporary) / "workspace"
            staging.mkdir()
            manifest = inspect_backup(values["path"], extract_to=staging)
            if digest(values["path"]) != values["sha256"]:
                raise ConflictError("Backup changed during restore. Select it again.")
            rebase_and_validate(staging, manifest["workspace"], root, device.identity())
            self.close()
            moved = False
            try:
                root.rename(rollback)
                moved = True
                staging.rename(root)
                self.__init__(root, device=device)
            except Exception:
                # Failed initialization can leave the restored catalog open.
                # Release every connection before moving folders on Windows.
                self.close()
                if moved:
                    if root.exists():
                        root.rename(Path(temporary) / "failed-workspace")
                    rollback.rename(root)
                self.__init__(root, device=device)
                self.auth.user = session_user
                self.auth.lock_minutes = session_lock_minutes
                raise
        return {"rollback_path": str(rollback), "restored": True}

    def export(self, payload):
        values = _validate(payload, ("case_id", "format", "path"))
        connection, _, pipelines = self.session(values["case_id"])
        run = pipelines.latest_for_case(values["case_id"])
        if run is None or not run.complete:
            raise PrerequisiteError("Complete the analysis before exporting results.")
        settings = self.get_settings({})
        options = {"preferences": settings["preferences"], "examiner_profile": settings["profile"]}
        if values["format"] == "JSON":
            path = write_json(connection, values["case_id"], values["path"], **options)
        elif values["format"] == "CSV":
            write_csv(connection, values["case_id"], values["path"], **options)
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
        path = contained(
            Path(stores.cases.get(values["case_id"]).workspace_path), Path(output.path)
        )
        if self.hasher.sha256(str(path)) != output.sha256:
            raise ConflictError("Stored raw output no longer matches its recorded SHA-256.")
        # Display a bounded preview; the exact complete bytes remain in the workspace.
        with path.open("rb") as stream:
            raw = stream.read(256 * 1024 + 1)
        return {
            "text": raw[: 256 * 1024].decode("utf-8", errors="replace"),
            "truncated": len(raw) > 256 * 1024,
            "sha256": output.sha256,
            "path": output.path,
        }

    def router(self):
        public = {
            "health",
            "auth_status",
            "auth_signup",
            "auth_login",
            "auth_logout",
            "auth_lock",
            "auth_unlock",
        }

        def authorize(command):
            if command not in public:
                self.auth.require_user()

        router = CommandRouter(before_dispatch=authorize)
        for command, method in (
            ("auth_status", "status"),
            ("auth_signup", "signup"),
            ("auth_login", "login"),
            ("auth_logout", "logout"),
            ("auth_lock", "lock"),
            ("auth_unlock", "unlock"),
            ("auth_touch", "touch"),
            ("change_password", "change_password"),
        ):
            router.register(
                command, lambda payload, method=method: getattr(self.auth, method)(payload)
            )
        router.register(
            "health",
            lambda payload: {
                "name": "FactumDB",
                "status": "ready",
                "protocol": 1,
                "application_configured": True,
            },
        )
        router.register("create_case", self.create_case)
        router.register("list_cases", self.list_cases)
        router.register("delete_case", self.delete_case)
        router.register("get_case_data", self.case_data)
        router.register("get_analysis_detail", self.analysis_detail)
        for name, kind in (("get_history_tables", "tables"), ("get_history_page", "page"), ("locate_history_record", "locate")):
            router.register(name, lambda payload, kind=kind: self.history_query(kind, payload))
        router.register("save_case_notes", self.save_case_notes)
        router.register("get_settings", self.get_settings)
        router.register("configure_settings", self.configure)
        router.register("configure_preferences", self.configure_preferences)
        router.register("configure_profile", self.configure_profile)
        router.register("storage_usage", self.storage_usage)
        router.register("backup_workspace", self.backup_workspace)
        router.register("inspect_workspace_backup", self.inspect_workspace_backup)
        router.register("restore_workspace", self.restore_workspace)
        router.register("export_case", self.export)
        router.register("read_tool_output", self.raw_output)
        for command in COMMAND_FIELDS:
            if command != "create_case":
                router.register(
                    command,
                    lambda payload, command=command: self.application_command(command, payload),
                )
        return router


class _QuietProgress:
    def publish(self, progress):
        # The desktop receives persisted transitions after each stage. stdout is
        # reserved exclusively for correlated JSON-lines responses.
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--native-verification",
        action="store_true",
        help="Enable the private Tauri Windows Hello exchange",
    )
    args = parser.parse_args()
    bridge = NativeVerificationBridge(sys.stdin, sys.stdout) if args.native_verification else None
    runtime = DesktopRuntime(
        args.workspace,
        device=device_security(verify_device=bridge.verify if bridge else None),
    )
    try:
        serve(sys.stdin, sys.stdout, runtime.router(), native_verification=bridge)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
