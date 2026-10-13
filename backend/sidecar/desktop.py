"""Configured desktop entry point. Owns a catalog and one database per case."""

import argparse
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import uuid
from functools import wraps
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
    require_backup_owner,
    usage,
)
from adapters.persistence.case_export import write_json
from adapters.persistence.sqlite_accounts import SqliteAccountStore
from adapters.persistence.sqlite_case_repository import SqliteCaseRepository
from adapters.persistence.sqlite_case_ownership import SqliteCaseOwnership
from adapters.persistence.sqlite_database import open_case_database
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
from sidecar.native_verification import NativeVerificationBridge
from sidecar.protocol import CommandRouter, SidecarRequest, serve
from sidecar.views import analysis_detail, case_view, case_preview


def preview_locked(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._preview_lock:
            return method(self, *args, **kwargs)
    return locked


class DesktopRuntime:
    def __init__(self, root, *, device=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = open_case_database(self.root / "catalog.db")
        self.auth = AuthenticationService(
            SqliteAccountStore(self.catalog), device or device_security()
        )
        self.cases = SqliteCaseRepository(self.catalog)
        self.ownership = SqliteCaseOwnership(self.catalog)
        self.workspace = FilesystemCaseWorkspace(self.root / "cases")
        self.ids, self.clock = UuidGenerator(), UtcClock()
        self.hasher = Sha256FileHasher()
        self.sessions = {}
        self.export_preview = None
        self.export_preparation = None
        self._background_reports = {}
        self._preview_lock = threading.RLock()
        self._preview_timer = None
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

    @preview_locked
    def close(self):
        self._clear_export_preview()
        self._clear_background_reports()
        for connection, *_ in self.sessions.values():
            connection.close()
        self.catalog.close()

    @preview_locked
    def _clear_export_preview(self):
        if self._preview_timer is not None:
            self._preview_timer.cancel()
            self._preview_timer = None
        if self.export_preview is not None:
            document = self.export_preview.get("document")
            if hasattr(document, "close"):
                document.close()
        self.export_preview = None
        if self.export_preparation is not None:
            try:
                self.export_preparation["steps"].close()
            finally:
                self.export_preparation["read_connection"].close()
            self.export_preparation = None

    def _park_export_preview(self):
        active = self.export_preparation or self.export_preview
        if active is None:
            return
        key = (active["case_id"], active["format"])
        self._dispose_background_report(key)
        self._background_reports[key] = {
            "preview": self.export_preview, "preparation": self.export_preparation,
            "timer": self._preview_timer,
        }
        self.export_preview = self.export_preparation = self._preview_timer = None

    def _activate_export_token(self, token):
        active = self.export_preparation or self.export_preview
        if active is not None and active["token"] == token:
            return
        for key, slot in list(self._background_reports.items()):
            saved = slot["preparation"] or slot["preview"]
            if saved is not None and saved["token"] == token:
                self._background_reports.pop(key)
                self._park_export_preview()
                self.export_preview, self.export_preparation, self._preview_timer = (
                    slot["preview"], slot["preparation"], slot["timer"],
                )
                return

    def _dispose_background_report(self, key):
        slot = self._background_reports.pop(key, None)
        if not slot:
            return
        if slot["timer"] is not None:
            slot["timer"].cancel()
        preview, job = slot["preview"], slot["preparation"]
        if preview is not None:
            preview["document"].close()
        if job is not None:
            try:
                job["steps"].close()
            finally:
                job["read_connection"].close()

    def _clear_background_reports(self):
        for key in list(self._background_reports):
            self._dispose_background_report(key)

    @preview_locked
    def _expire_export_preview(self):
        for key, slot in list(self._background_reports.items()):
            cached = slot["preparation"] or slot["preview"]
            if cached is not None and cached["expires"] <= time.monotonic():
                self._dispose_background_report(key)
        active = self.export_preparation or self.export_preview
        if active is not None and active["expires"] <= time.monotonic():
            self._clear_export_preview()


    def session(self, case_id):
        from adapters.persistence.sqlite_integration import build_sqlite_application_stores
        safe_component(case_id, "case id")
        self.ownership.require_owner(case_id, self.auth.require_actor()["actor_id"])
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
        from sidecar.composition import (
            PipelineDependencies, build_application_services, build_tool_adapters,
        )
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
        case_ids = self.ownership.case_ids(self.auth.require_actor()["actor_id"])
        result = []
        for case_id in case_ids:
            _, stores, pipelines = self.session(case_id)
            case = stores.cases.get(case_id)
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
        self.ownership.assign(response.case_id, self.auth.require_actor()["actor_id"])
        self.session(response.case_id)
        return {"case_id": response.case_id}

    def case_preview(self, payload):
        case_id = _validate(payload, ("case_id",))["case_id"]
        connection, stores, pipelines = self.session(case_id)
        return case_preview(case_id, connection, stores, pipelines)

    def case_data(self, payload):
        case_id = _validate(payload, ("case_id",))["case_id"]
        connection, stores, pipelines = self.session(case_id)
        return case_view(case_id, connection, stores, pipelines)

    def case_header(self, payload):
        case_id = _validate(payload, ("case_id",))["case_id"]
        connection, stores, pipelines = self.session(case_id)
        return case_preview(case_id, connection, stores, pipelines, fast=True)

    def screen_query(self, command, payload):
        from adapters.persistence.sqlite_screen_repository import ScreenRepository
        from adapters.persistence.case_export import _row, _TABLES
        from sidecar.views import _present, _findings, history_details
        allowed = {'case_id', 'kind', 'offset', 'limit', 'bucket', 'identity'}
        if set(payload) - allowed:
            raise ValueError('Unsupported screen query fields')
        case_id = _validate({'case_id': payload.get('case_id')}, ('case_id',))['case_id']
        connection, _, _ = self.session(case_id)
        repository = ScreenRepository(connection)
        kind = payload.get('kind')
        if kind in {'tool_runs', 'reports'} and command in {'page', 'locate'}:
            from_clause = 'tool_runs' if kind=='tool_runs' else 'reports'
            sort = 'started_at,tool_run_id' if kind=='tool_runs' else 'created_at,report_id'
            id_column = 'tool_run_id' if kind=='tool_runs' else 'report_id'
            if command == 'locate':
                identity = _validate({'identity': payload.get('identity')}, ('identity',))['identity']
                row = connection.execute(f'SELECT position FROM (SELECT {id_column},row_number() OVER (ORDER BY {sort})-1 AS position FROM {from_clause} WHERE case_id=?) WHERE {id_column}=?', (case_id, identity)).fetchone()
                if row is None:
                    raise NotFoundError('Selected item not found')
                return dict(offset=row[0] // 100 * 100)
            offset,limit = payload.get('offset',0),payload.get('limit',100)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError('Invalid page bounds')
            total = connection.execute(f'SELECT count(*) FROM {from_clause} WHERE case_id=?', (case_id,)).fetchone()[0]
            items = [_row(r) for r in connection.execute(f'SELECT * FROM {from_clause} WHERE case_id=? ORDER BY {sort} LIMIT ? OFFSET ?', (case_id,limit,offset))]
            return _present(dict(items=items,total=total,offset=offset,limit=limit))
        if command == 'summary':
            for stage in ('grouping','correlation','reconstruction','reconciliation'):
                repository.legacy_summary(case_id, stage)
            return _present(dict(summaries=repository.summaries(case_id)))
        if command == 'coverage':
            if kind not in {'grouping', 'reconciliation'}:
                raise ValueError('Unsupported coverage kind')
            repository.ensure(case_id, (kind,))
            row = connection.execute('SELECT coverage_json FROM screen_coverage WHERE case_id=? AND stage=?', (case_id, kind)).fetchone()
            if row is None:
                row = connection.execute("SELECT json_extract(result_json,'$.coverage') FROM analysis_results WHERE case_id=? AND stage=?", (case_id, kind)).fetchone()
                if row and row[0]:
                    with connection:
                        connection.execute('INSERT OR REPLACE INTO screen_coverage VALUES (?,?,?)', (case_id,kind,row[0]))
            return _present(dict(coverage=json.loads(row[0]) if row else None))
        if command == 'locate':
            identity = _validate({'identity': payload.get('identity')}, ('identity',))['identity']
            return repository.locate(case_id, kind, identity, payload.get('bucket'))
        if command == 'detail':
            identity = _validate({'identity': payload.get('identity')}, ('identity',))['identity']
            detail = repository.detail(case_id, kind, identity, payload.get('bucket'))
            if kind == 'histories':
                result = history_details(connection, case_id, [detail])[0]
                comparisons = repository.page(case_id, 'comparisons', identity=identity)
                result['detail']['comparisons'] = comparisons['items']
                result['detail']['comparison_count'] = comparisons['total']
                return result
            found = {}; _findings(detail, found)
            return _present(dict(detail=detail, findings=list(found.values())))
        if command == 'context':
            if kind not in {'timeline', 'record', 'pipeline', 'prov', 'report', 'gaps'}:
                raise ValueError('Unsupported screen context')
            tables = {}
            names = {'timeline': {'schemas', 'schema_columns'}, 'record': {'schemas', 'schema_columns'},
                     'pipeline': {'tool_runs'}, 'prov': {'tool_runs'}, 'report': {'reports'}, 'gaps': set()}[kind]
            for name, sql in _TABLES:
                if name in names:
                    if kind=='pipeline' and name=='tool_runs':
                        sql = 'SELECT * FROM (SELECT * FROM tool_runs WHERE case_id=? ORDER BY started_at DESC,tool_run_id DESC LIMIT 100) ORDER BY started_at,tool_run_id'
                    tables[name] = [_row(r) for r in connection.execute(sql, (case_id,))]
            if kind == 'report':
                tables['reports'] = [_row(r) for r in connection.execute('SELECT * FROM reports WHERE case_id=? ORDER BY created_at,report_id', (case_id,))]
            return _present(dict(tables=tables))
        if kind == 'finding_groups':
            groups = repository.groups(case_id)
            offset, limit = payload.get('offset', 0), payload.get('limit', 100)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError('Invalid finding group page bounds')
            return _present(dict(items=groups[offset:offset+limit], total=len(groups), offset=offset, limit=limit,
                                 counts=dict(warning=sum(g['severity']=='warning' for g in groups), notice=sum(g['severity']=='notice' for g in groups)), summaries=repository.summaries(case_id)))
        if kind in {'warning_groups', 'warning_entries'}:
            offset, limit = payload.get('offset', 0), payload.get('limit', 100)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError('Invalid warning page bounds')
            if kind == 'warning_groups':
                groups = [dict(id=json.dumps([r[0], r[1] or '', r[2] or ''], separators=(',', ':')), code=r[0], evidenceId=r[1] or '', toolRunId=r[2] or '', occurrences=r[3], entries=[])
                          for r in connection.execute('SELECT code,evidence_id,tool_run_id,count(*) FROM warnings WHERE case_id=? GROUP BY code,evidence_id,tool_run_id ORDER BY code,evidence_id,tool_run_id', (case_id,))]
                return dict(items=groups[offset:offset+limit], total=len(groups), offset=offset, limit=limit)
            bucket = payload.get('bucket')
            code, evidence, tool = json.loads(bucket)
            where = "case_id=? AND code=? AND coalesce(evidence_id,'')=? AND coalesce(tool_run_id,'')=?"
            args = (case_id, code, evidence, tool)
            total = connection.execute(f'SELECT count(*) FROM warnings WHERE {where}', args).fetchone()[0]
            items = [_row(r) for r in connection.execute(f'SELECT * FROM warnings WHERE {where} ORDER BY warning_id LIMIT ? OFFSET ?', (*args, limit, offset))]
            return _present(dict(items=items, total=total, offset=offset, limit=limit))
        result = repository.page(case_id, kind, payload.get('offset', 0), payload.get('limit', 100), payload.get('bucket'), payload.get('identity'))
        if kind == 'history_steps':
            result['events'] = history_details(connection, case_id, [dict(steps=result['items'])])[0]['detail']['events']
        return _present(result)

    def delete_case(self, payload):
        self.auth.require_user()
        values = _validate(payload, ("case_id", "confirmation"))
        case_id = safe_component(values["case_id"], "case id")
        self.ownership.require_owner(case_id, self.auth.require_actor()["actor_id"])
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
        from sidecar.main import build_router
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
        connection, stores, pipelines = self.session(case_id)
        if command == "register_evidence":
            self._require_owned_path(values["source_path"])
        elif command == "verify_evidence":
            evidence = stores.evidence.get(case_id, values["evidence_id"])
            if evidence is not None:
                self._require_owned_path(evidence.source_path)
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
        try:
            self._require_exclusive_workspace()
            workspace_operations_available = True
        except PermissionError:
            workspace_operations_available = False
        return {
            "workspace": str(self.root),
            "tools": self.settings,
            "bundled_tools": self.bundled_tools,
            "profile": details["profile"],
            "preferences": {**DEFAULTS, **details["preferences"]},
            "workspace_operations_available": workspace_operations_available,
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
        return usage(
            self.root, case_ids=self.ownership.case_ids(self.auth.require_actor()["actor_id"]),
        )

    def _require_owned_path(self, path):
        resolved = Path(path).expanduser().resolve()
        if resolved.is_relative_to(self.root):
            relative = resolved.relative_to(self.root)
            if len(relative.parts) < 2 or relative.parts[0] != "cases":
                raise PermissionError("This path is not in an owned case.")
            self.ownership.require_owner(relative.parts[1], self.auth.require_actor()["actor_id"])

    def _require_exclusive_workspace(self):
        self.ownership.require_exclusive_workspace(self.auth.require_actor()["actor_id"])

    def workspace_folder(self, payload):
        _validate(payload, ())
        self._require_exclusive_workspace()
        return {"workspace": str(self.root)}

    def backup_workspace(self, payload):
        self._require_exclusive_workspace()
        path = _validate(payload, ("path",))["path"]
        self.ensure_storage_idle()
        return create_backup(self.root, path)

    def inspect_workspace_backup(self, payload):
        self._require_exclusive_workspace()
        path = _validate(payload, ("path",))["path"]
        checksum = digest(path)
        manifest = inspect_backup(path)
        require_backup_owner(
            path, self.auth.accounts.find(self.auth.require_user()["username"].lower()),
        )
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
        self._require_exclusive_workspace()
        for row in self.catalog.execute("SELECT case_id FROM cases"):
            _, _, pipelines = self.session(row[0])
            run = pipelines.latest_for_case(row[0])
            if run and any(stage.status.value == "running" for stage in run.stages):
                raise ConflictError(
                    "Finish the running analysis stage before backing up or restoring"
                )

    def restore_workspace(self, payload):
        self._require_exclusive_workspace()
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
            require_backup_owner(
                values["path"], self.auth.accounts.find(self.auth.require_user()["username"].lower()),
            )
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

    def _export_options(self, payload, *, destination=False):
        required = ("case_id", "format", "path") if destination else ("case_id", "format")
        values = _validate(
            {k: v for k, v in payload.items() if k not in {"redacted", "sections", "preview_token", "profile"}},
            required,
        )
        redacted = payload.get("redacted", True)
        if not isinstance(redacted, bool):
            raise ValueError("redacted must be a boolean")
        if values["format"] not in {"JSON", "PDF"}:
            raise ValueError("Supported export formats are JSON and PDF")
        detail = "full" if values["format"] == "JSON" else "summary"
        if "profile" in payload and payload["profile"] != detail:
            raise ValueError("Report detail is fixed by the export format")
        if payload.get("sections") is not None:
            raise ValueError("Section selection is unavailable: JSON is complete and PDF is a summary")
        return values, {"redacted": redacted}

    def export_definitions(self, payload):
        from adapters.persistence.summary_report import export_definitions
        if payload:
            raise ValueError("Export definitions take no arguments")
        return export_definitions()

    def _prepare_report_steps(self, connection, case_id, format, settings, options):
        from adapters.persistence.investigator_export import prepare_projection_steps
        from adapters.persistence.summary_report import prepare_summary_steps
        document = None
        try:
            if format == "JSON":
                document = yield from prepare_projection_steps(
                    connection, case_id, profile="full", **settings, **options
                )
            else:
                document = yield from prepare_summary_steps(connection, case_id, **settings, **options)
                yield from document.prepare_pdf_steps()
            return document
        except BaseException:
            if document is not None:
                document.close()
            raise

    def _export_source(self, case_id):
        connection, _, pipelines = self.session(case_id)
        run = pipelines.latest_for_case(case_id)
        if run is None or not run.complete:
            raise PrerequisiteError("Complete the analysis before exporting results.")
        settings = self.get_settings({})
        return connection, {"preferences": settings["preferences"], "examiner_profile": settings["profile"]}

    def _export_fingerprint(self, connection, case_id, settings):
        value = {"connection": id(connection), "case_id": case_id,
                 "data_version": connection.execute("PRAGMA data_version").fetchone()[0],
                 "total_changes": connection.total_changes, "settings": settings,
                 "actor": self.auth.require_actor()["actor_id"]}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    @preview_locked
    def preview_export(self, payload):
        progressive = payload.get("progressive", False)
        if not isinstance(progressive, bool):
            raise ValueError("progressive must be a boolean")
        payload = {k: v for k, v in payload.items() if k != "progressive"}
        values, options = self._export_options(payload)
        connection, settings = self._export_source(values["case_id"])
        for saved_key in list(self._background_reports):
            if saved_key[0] != values["case_id"]:
                self._dispose_background_report(saved_key)
        key = (values["case_id"], values["format"])
        slot = self._background_reports.get(key)
        if slot is not None and (slot["preparation"] or slot["preview"])["options"] == options:
            active = slot["preparation"] or slot["preview"]
            if (active["fingerprint"] == self._export_fingerprint(connection, values["case_id"], settings)
                    and active["expires"] > time.monotonic()):
                self._background_reports.pop(key)
                self._park_export_preview()
                self.export_preview, self.export_preparation, self._preview_timer = (
                    slot["preview"], slot["preparation"], slot["timer"],
                )
                if self.export_preview is not None:
                    return self._preview_page(1)
                if progressive:
                    return {"preparation_token": active["token"], "stage": "resuming", "processed": 0}
                while self.export_preparation is not None:
                    result = self.export_preview_status({"preparation_token": active["token"]})
                return result
            self._dispose_background_report(key)
        active = self.export_preparation or self.export_preview
        if active is not None and active["case_id"] == values["case_id"] and active["format"] != values["format"]:
            self._park_export_preview()
        else:
            self._clear_export_preview()
        fingerprint = self._export_fingerprint(connection, values["case_id"], settings)
        if progressive:
            database = connection.execute("PRAGMA database_list").fetchone()[2]
            read_connection = sqlite3.connect(
                Path(database).as_uri() + "?mode=ro", uri=True, check_same_thread=False
            )
            read_connection.row_factory = sqlite3.Row
            read_connection.execute("PRAGMA query_only=ON")
            read_connection.execute("PRAGMA cache_size=-2048")
            self.export_preparation = {
                "token": uuid.uuid4().hex, "case_id": values["case_id"],
                "format": values["format"], "options": options, "fingerprint": fingerprint,
                "expires": time.monotonic() + 600,
                "read_connection": read_connection,
                "steps": self._prepare_report_steps(read_connection, values["case_id"],
                                                     values["format"], settings, options),
            }
            self._preview_timer = threading.Timer(600, self._expire_export_preview)
            self._preview_timer.daemon = True
            self._preview_timer.start()
            return {"preparation_token": self.export_preparation["token"],
                    "stage": "starting", "processed": 0}
        steps = self._prepare_report_steps(connection, values["case_id"], values["format"], settings, options)
        while True:
            try:
                next(steps)
            except StopIteration as completed:
                document = completed.value
                break
        try:
            if fingerprint != self._export_fingerprint(connection, values["case_id"], settings):
                raise PrerequisiteError("Case data changed; refresh the export preview")
        except BaseException:
            document.close()
            raise
        self.export_preview = {
            "token": uuid.uuid4().hex, "case_id": values["case_id"],
            "format": values["format"], "options": options, "document": document,
            "expires": time.monotonic() + 600, "fingerprint": fingerprint,
        }
        self._preview_timer = threading.Timer(600, self._expire_export_preview)
        self._preview_timer.daemon = True
        self._preview_timer.start()
        return self._preview_page(1)

    @preview_locked
    def export_preview_status(self, payload, *, budget=0.15):
        if set(payload) != {"preparation_token"}:
            raise ValueError("Invalid preview preparation request")
        self._activate_export_token(payload["preparation_token"])
        job = self.export_preparation
        if job is None or job["token"] != payload["preparation_token"]:
            raise PrerequisiteError("Refresh the export preview")
        connection, settings = self._export_source(job["case_id"])
        if job["fingerprint"] != self._export_fingerprint(connection, job["case_id"], settings):
            self._clear_export_preview()
            raise PrerequisiteError("Case data changed; refresh the export preview")
        # Renew active jobs without creating a timer thread for every batch.
        if job["expires"] - time.monotonic() < 300:
            job["expires"] = time.monotonic() + 600
            if self._preview_timer is not None:
                self._preview_timer.cancel()
            self._preview_timer = threading.Timer(600, self._expire_export_preview)
            self._preview_timer.daemon = True
            self._preview_timer.start()
        deadline = time.monotonic() + budget
        document = None
        try:
            while True:
                try:
                    progress = next(job["steps"])
                except StopIteration as completed:
                    document = completed.value
                    break
                if time.monotonic() >= deadline:
                    return {"preparation_token": job["token"], **progress}
            if job["fingerprint"] != self._export_fingerprint(connection, job["case_id"], settings):
                raise PrerequisiteError("Case data changed; refresh the export preview")
        except BaseException:
            if document is not None:
                document.close()
            self._clear_export_preview()
            raise
        job["read_connection"].close()
        self.export_preparation = None
        if self._preview_timer is not None:
            self._preview_timer.cancel()
        self.export_preview = {k: v for k, v in job.items() if k not in {"steps", "read_connection"}}
        self.export_preview.update(document=document, expires=time.monotonic() + 600)
        self._preview_timer = threading.Timer(600, self._expire_export_preview)
        self._preview_timer.daemon = True
        self._preview_timer.start()
        return self._preview_page(1)

    @preview_locked
    def cancel_export_preview(self, payload):
        if set(payload) != {"preparation_token"}:
            raise ValueError("Invalid preview cancellation request")
        self._activate_export_token(payload["preparation_token"])
        active = self.export_preparation or self.export_preview
        if active and active["token"] == payload["preparation_token"]:
            self._clear_export_preview()
        return {"cancelled": True}

    @preview_locked
    def _preview_page(self, page):
        from adapters.persistence.summary_report import SummaryProjection
        preview = self.export_preview
        if preview is None or preview["expires"] < time.monotonic():
            self._clear_export_preview()
            raise PrerequisiteError("Refresh the export preview")
        document = preview["document"]
        pages = document.pages if isinstance(document, SummaryProjection) else 1
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= pages:
            raise ValueError("Invalid preview page")
        return {"preview_token": preview["token"], "page": page, "pages": pages,
                "pages_complete": True,
                "has_more": page < pages,
                "detail": "summary" if isinstance(document, SummaryProjection) else "full",
                "counts": document.metadata["counts"],
                "classification_totals": document.metadata.get("classification_totals"),
                "size_bytes": document.pdf_size if isinstance(document, SummaryProjection) else document.json_size,
                "manifest": {k: document.metadata[k] for k in (
                    "case_id", "exported_at", "engine_revision", "analysis_format_version"
                )},
                "format": preview["format"], "redacted": preview["options"]["redacted"]}

    @preview_locked
    def export_preview_pdf(self, payload):
        from adapters.persistence.summary_report import SummaryProjection
        if set(payload) != {"preview_token", "offset", "length"}:
            raise ValueError("Invalid PDF preview request")
        self.export_preview_page({"preview_token": payload["preview_token"], "page": 1})
        document = self.export_preview["document"]
        if not isinstance(document, SummaryProjection):
            raise ValueError("This preview is not a PDF")
        offset, length = payload["offset"], payload["length"]
        if (not isinstance(offset, int) or isinstance(offset, bool) or
                not isinstance(length, int) or isinstance(length, bool) or
                not 0 <= offset < document.pdf_size or not 1 <= length <= 262144):
            raise ValueError("Invalid PDF preview byte range")
        with document.pdf_path.open("rb") as source:
            source.seek(offset)
            content = source.read(length)
        return {"offset": offset, "total_bytes": document.pdf_size,
                "data": base64.b64encode(content).decode("ascii")}

    @preview_locked
    def export_preview_page(self, payload):
        if set(payload) != {"preview_token", "page"}:
            raise ValueError("Invalid preview request")
        self._activate_export_token(payload["preview_token"])
        preview = self.export_preview
        if preview is None or payload["preview_token"] != preview["token"]:
            raise PrerequisiteError("Refresh the export preview")
        connection, settings = self._export_source(preview["case_id"])
        if preview["fingerprint"] != self._export_fingerprint(connection, preview["case_id"], settings):
            self._clear_export_preview()
            raise PrerequisiteError("Case data changed; refresh the export preview")
        return self._preview_page(payload["page"])

    @preview_locked
    def export(self, payload):
        values, options = self._export_options(payload, destination=True)
        connection, settings = self._export_source(values["case_id"])
        self._require_owned_path(values["path"])
        actor = self.auth.require_actor()
        document = None
        if "preview_token" in payload:
            self._activate_export_token(payload["preview_token"])
            preview = self.export_preview
            if (preview is None or payload["preview_token"] != preview["token"]
                    or preview["expires"] < time.monotonic()
                    or preview["case_id"] != values["case_id"]
                    or preview["format"] != values["format"] or preview["options"] != options
                    or preview["fingerprint"] != self._export_fingerprint(connection, values["case_id"], settings)):
                raise PrerequisiteError("Refresh the export preview before exporting")
            document = preview["document"]
        options = {**settings, **options, "prepared_document": document}
        if values["format"] == "JSON":
            path = write_json(connection, values["case_id"], values["path"], profile="full", **options, **actor)
        else:
            from adapters.persistence.pdf_report import write_pdf
            if document is None:
                options.pop("prepared_document")
                options.pop("prepared_document", None)
                steps = self._prepare_report_steps(connection, values["case_id"], "PDF", settings,
                                                  {"redacted": options["redacted"]})
                while True:
                    try:
                        next(steps)
                    except StopIteration as completed:
                        document = completed.value
                        break
            try:
                path = write_pdf(connection, values["case_id"], values["path"], document,
                                 self.clock.now(), **actor)
            finally:
                if "preview_token" not in payload:
                    document.close()
        self._clear_export_preview()
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
        if path.stat().st_size != output.size_bytes:
            raise ConflictError("Stored raw output no longer matches its recorded size.")
        # Display a bounded preview; the exact complete bytes remain in the workspace.
        with path.open("rb") as stream:
            raw = stream.read(256 * 1024 + 1)
        return {
            "text": raw[: 256 * 1024].decode("utf-8", errors="replace"),
            "truncated": len(raw) > 256 * 1024,
            "sha256": output.sha256,
            "path": output.path,
        }

    @preview_locked
    def prepare_background_report(self, payload):
        values = _validate(payload, ("case_id", "format"))
        if values["format"] not in {"PDF", "JSON"}:
            raise ValueError("Supported export formats are JSON and PDF")
        connection, settings = self._export_source(values["case_id"])
        key = (values["case_id"], values["format"])
        if self.export_preview is not None and self.export_preview["case_id"] != values["case_id"]:
            self._clear_export_preview()
        fingerprint = self._export_fingerprint(connection, values["case_id"], settings)
        if (self.export_preparation is not None and self.export_preparation["case_id"] == key[0]
                and self.export_preparation["format"] == key[1]
                and self.export_preparation["options"]["redacted"]
                and self.export_preparation["fingerprint"] == fingerprint):
            return {"preparation_token": self.export_preparation["token"], "stage": "foreground", "processed": 0}
        if (self.export_preview is not None and self.export_preview["case_id"] == key[0]
                and self.export_preview["format"] == key[1]
                and self.export_preview["options"]["redacted"]
                and self.export_preview["fingerprint"] == fingerprint):
            return self._preview_page(1)
        # Only this case's two sharing copies are retained, on temporary disk.
        for other, slot in list(self._background_reports.items()):
            job = slot["preparation"] or slot["preview"]
            if (other[0] != key[0] or job["fingerprint"] != fingerprint
                    or job["expires"] <= time.monotonic()):
                self._dispose_background_report(other)
        slot = self._background_reports.get(key, {"preview": None, "preparation": None, "timer": None})
        foreground = (self.export_preview, self.export_preparation, self._preview_timer)
        self.export_preview, self.export_preparation, self._preview_timer = (
            slot["preview"], slot["preparation"], slot["timer"],
        )
        try:
            if self.export_preview is not None:
                return self._preview_page(1)
            if self.export_preparation is None:
                return self.preview_export({**values, "redacted": True, "progressive": True})
            return self.export_preview_status(
                {"preparation_token": self.export_preparation["token"]}, budget=0.025,
            )
        except BaseException:
            self._clear_export_preview()
            raise
        finally:
            if self.export_preview is not None or self.export_preparation is not None:
                self._background_reports[key] = {
                    "preview": self.export_preview, "preparation": self.export_preparation,
                    "timer": self._preview_timer,
                }
            else:
                self._background_reports.pop(key, None)
            self.export_preview, self.export_preparation, self._preview_timer = foreground

    @preview_locked
    def claim_background_report(self, payload):
        values, options = self._export_options(payload)
        connection, settings = self._export_source(values["case_id"])
        key = (values["case_id"], values["format"])
        active = self.export_preview
        if (active is not None and active["case_id"] == values["case_id"]
                and active["format"] == values["format"] and active["options"] == options
                and active["expires"] > time.monotonic()
                and active["fingerprint"] == self._export_fingerprint(connection, values["case_id"], settings)):
            return self._preview_page(1)
        slot = self._background_reports.get(key)
        if slot is None or slot["preview"] is None or not options["redacted"]:
            return None
        preview = slot["preview"]
        if (preview["expires"] <= time.monotonic() or
                preview["fingerprint"] != self._export_fingerprint(connection, values["case_id"], settings)):
            self._dispose_background_report(key)
            return None
        self._background_reports.pop(key)
        self._park_export_preview()
        self.export_preview = preview
        self._preview_timer = slot["timer"]
        return self._preview_page(1)

    @preview_locked
    def cancel_background_reports(self, payload):
        values = _validate(payload, ("case_id",))
        self.ownership.require_owner(values["case_id"], self.auth.require_actor()["actor_id"])
        for key in list(self._background_reports):
            if key[0] == values["case_id"]:
                self._dispose_background_report(key)
        return {"cancelled": True}

    def warm_dependencies(self, payload):
        """Import one feature bundle without opening a case or running analysis."""
        from importlib import import_module
        values = _validate(payload, ("kind",))
        modules = {
            "report": "adapters.persistence.summary_report",
            "pdf": "adapters.persistence.pdf_report",
            "analysis": "sidecar.composition",
        }
        if values["kind"] not in modules:
            raise ValueError("Unknown dependency bundle")
        import_module(modules[values["kind"]])
        return {"kind": values["kind"], "ready": True}

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
            self._expire_export_preview()
            if command not in public:
                self.auth.require_user()
            if command in {"auth_logout", "auth_lock"}:
                self._clear_export_preview()
                self._clear_background_reports()
                for connection, *_ in self.sessions.values():
                    connection.close()
                self.sessions.clear()

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
        router.register("get_case_preview", self.case_preview)
        router.register("get_case_header", self.case_header)
        router.register("get_screen_page", lambda payload: self.screen_query('page', payload))
        router.register("get_screen_detail", lambda payload: self.screen_query('detail', payload))
        router.register("get_screen_context", lambda payload: self.screen_query('context', payload))
        router.register("locate_screen_item", lambda payload: self.screen_query('locate', payload))
        router.register("get_screen_coverage", lambda payload: self.screen_query('coverage', payload))
        router.register("get_screen_summary", lambda payload: self.screen_query('summary', payload))
        router.register("get_analysis_detail", self.analysis_detail)
        for name, kind in (("get_history_tables", "tables"), ("get_history_page", "page"), ("locate_history_record", "locate")):
            router.register(name, lambda payload, kind=kind: self.history_query(kind, payload))
        router.register("save_case_notes", self.save_case_notes)
        router.register("prepare_background_report", self.prepare_background_report)
        router.register("claim_background_report", self.claim_background_report)
        router.register("cancel_background_reports", self.cancel_background_reports)
        router.register("warm_dependencies", self.warm_dependencies)
        router.register("get_settings", self.get_settings)
        router.register("configure_settings", self.configure)
        router.register("configure_preferences", self.configure_preferences)
        router.register("configure_profile", self.configure_profile)
        router.register("storage_usage", self.storage_usage)
        router.register("get_workspace_folder", self.workspace_folder)
        router.register("backup_workspace", self.backup_workspace)
        router.register("inspect_workspace_backup", self.inspect_workspace_backup)
        router.register("restore_workspace", self.restore_workspace)
        router.register("export_case", self.export)
        router.register("preview_export", self.preview_export)
        router.register("export_preview_status", self.export_preview_status)
        router.register("cancel_export_preview", self.cancel_export_preview)
        router.register("get_export_definitions", self.export_definitions)
        router.register("export_preview_pdf", self.export_preview_pdf)
        router.register("export_preview_page", self.export_preview_page)
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
