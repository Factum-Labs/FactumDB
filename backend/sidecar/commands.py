"""Validated JSON commands over injected application services."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from core.application.models import (
    CreateCaseRequest, RegisterEvidenceRequest, VerifyEvidenceRequest,
)
from core.application.orchestration.models import PipelineRun
from core.application.orchestration.pipeline import AnalysisOrchestrator
from core.application.use_cases.cases import CreateCaseUseCase
from core.application.use_cases.evidence import RegisterEvidenceUseCase, VerifyEvidenceUseCase
from core.domain.models.evidence import EvidenceFile
from sidecar.protocol import CommandRouter


class InvalidPayloadError(ValueError):
    """The command payload does not match its public contract."""


class ApplicationNotConfiguredError(RuntimeError):
    """Production repositories and application services have not been supplied."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationServices:
    create_case: CreateCaseUseCase
    register_evidence: RegisterEvidenceUseCase
    verify_evidence: VerifyEvidenceUseCase
    pipeline: AnalysisOrchestrator


COMMAND_FIELDS = {
    "create_case": ("case_name", "examiner"),
    "register_evidence": ("case_id", "source_path"),
    "verify_evidence": ("case_id", "evidence_id"),
    "start_pipeline": ("case_id",),
    "run_next_stage": ("run_id",),
    "get_pipeline_status": ("run_id",),
    "cancel_pipeline": ("run_id",),
    "retry_pipeline": ("run_id",),
}


def _validate(payload: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, str]:
    if set(payload) - set(fields):
        raise InvalidPayloadError("payload contains unsupported fields")
    values = {}
    for field in fields:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise InvalidPayloadError(f"{field} must be a non-empty string")
        # Preserve valid filenames containing leading/trailing spaces.
        values[field] = value if field == "source_path" else value.strip()
    return values


def _evidence_result(evidence: EvidenceFile) -> dict[str, object]:
    return {
        "evidence_id": evidence.id, "case_id": evidence.case_id,
        "source_path": evidence.source_path, "filename": evidence.filename,
        "kind": evidence.kind.value, "size_bytes": evidence.size_bytes,
        "source_sha256": evidence.source_sha256,
        "registered_at": evidence.registered_at.isoformat(),
        "verification_status": evidence.verification_status.value,
        "working_copy_path": evidence.working_copy_path,
        "working_copy_sha256": evidence.working_copy_sha256,
        "acquisition_method": evidence.acquisition_method,
        "verified": evidence.is_verified(),
    }


def _pipeline_result(run: PipelineRun) -> dict[str, object]:
    result = asdict(run)
    result["run_id"] = result.pop("id")
    result["created_at"] = run.created_at.isoformat()
    result["complete"] = run.complete
    result["stopped"] = run.stopped
    return result


def register_application_commands(
    router: CommandRouter, services: ApplicationServices | None,
) -> None:
    def handler_for(command: str):
        def handle(payload: Mapping[str, object]) -> object:
            values = _validate(payload, COMMAND_FIELDS[command])
            if services is None:
                raise ApplicationNotConfiguredError("application services are not configured")
            if command == "create_case":
                response = services.create_case.execute(
                    CreateCaseRequest(values["case_name"], values["examiner"]),
                )
                return {
                    "case_id": response.case_id, "case_name": response.case_name,
                    "examiner": response.examiner, "created_at": response.created_at,
                    "workspace_path": response.case.workspace_path,
                }
            if command == "register_evidence":
                response = services.register_evidence.execute(
                    RegisterEvidenceRequest(values["case_id"], values["source_path"]),
                )
                return _evidence_result(response.evidence)
            if command == "verify_evidence":
                response = services.verify_evidence.execute(
                    VerifyEvidenceRequest(values["case_id"], values["evidence_id"]),
                )
                return _evidence_result(response.evidence)
            if command == "start_pipeline":
                return _pipeline_result(services.pipeline.start(values["case_id"]))
            operations = {
                "run_next_stage": services.pipeline.run_next,
                "get_pipeline_status": services.pipeline.get_status,
                "cancel_pipeline": services.pipeline.request_cancel,
                "retry_pipeline": services.pipeline.retry_failed,
            }
            return _pipeline_result(operations[command](values["run_id"]))
        return handle

    for command in COMMAND_FIELDS:
        router.register(command, handler_for(command))
