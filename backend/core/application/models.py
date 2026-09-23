"""Request, response, and transfer models for the application boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import PurePath

from core.domain.models.canonical import BinlogEvent, PhysicalRecord, Schema, TransactionMarker


class EvidenceKind(StrEnum):
    IBD = "ibd"
    BINLOG = "binlog"
    BINLOG_INDEX = "binlog_index"


class VerificationStatus(StrEnum):
    REGISTERED = "registered"
    VERIFIED = "verified"
    HASH_MISMATCH = "hash_mismatch"


def _required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _sha256(value: str) -> str:
    cleaned = value.lower()
    if len(cleaned) != 64 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError("sha256 must be a 64-character hexadecimal digest")
    return cleaned


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    name: str
    examiner: str
    created_at: datetime
    workspace_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "case id"))
        object.__setattr__(self, "name", _required(self.name, "case name"))
        object.__setattr__(self, "examiner", _required(self.examiner, "examiner"))
        object.__setattr__(
            self, "workspace_path", _required(self.workspace_path, "workspace path")
        )
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    id: str
    case_id: str
    source_path: str
    filename: str
    kind: EvidenceKind
    size_bytes: int
    source_sha256: str
    registered_at: datetime
    verification_status: VerificationStatus = VerificationStatus.REGISTERED
    working_copy_path: str | None = None
    working_copy_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "evidence id"))
        object.__setattr__(self, "case_id", _required(self.case_id, "case id"))
        object.__setattr__(self, "source_path", _required(self.source_path, "source path"))
        object.__setattr__(self, "filename", _required(self.filename, "filename"))
        object.__setattr__(self, "source_sha256", _sha256(self.source_sha256))
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        if self.registered_at.tzinfo is None:
            raise ValueError("registered_at must be timezone-aware")
        if PurePath(self.source_path).name != self.filename:
            raise ValueError("filename must match the source path")
        if self.working_copy_sha256 is not None:
            object.__setattr__(self, "working_copy_sha256", _sha256(self.working_copy_sha256))
        if self.verification_status is VerificationStatus.REGISTERED:
            if self.working_copy_path is not None or self.working_copy_sha256 is not None:
                raise ValueError("registered evidence cannot have working-copy details")
        elif self.working_copy_path is None or self.working_copy_sha256 is None:
            raise ValueError("a verification result requires working-copy details")

    @property
    def verified_working_path(self) -> str | None:
        if self.verification_status is VerificationStatus.VERIFIED:
            return self.working_copy_path
        return None

    def with_verification(self, path: str, digest: str) -> EvidenceFile:
        normalized = _sha256(digest)
        status = (
            VerificationStatus.VERIFIED
            if normalized == self.source_sha256
            else VerificationStatus.HASH_MISMATCH
        )
        return replace(
            self,
            verification_status=status,
            working_copy_path=_required(path, "working-copy path"),
            working_copy_sha256=normalized,
        )


@dataclass(frozen=True, slots=True)
class CreateCaseRequest:
    name: str
    examiner: str


@dataclass(frozen=True, slots=True)
class CreateCaseResponse:
    case: Case


@dataclass(frozen=True, slots=True)
class EvidenceMetadata:
    canonical_path: str
    filename: str
    size_bytes: int
    kind: EvidenceKind


@dataclass(frozen=True, slots=True)
class RegisterEvidenceRequest:
    case_id: str
    source_path: str


@dataclass(frozen=True, slots=True)
class RegisterEvidenceResponse:
    evidence: EvidenceFile


@dataclass(frozen=True, slots=True)
class VerifyEvidenceRequest:
    case_id: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class VerifyEvidenceResponse:
    evidence: EvidenceFile

    @property
    def verified(self) -> bool:
        return self.evidence.verified_working_path is not None


@dataclass(frozen=True, slots=True)
class EvidenceStageRequest:
    case_id: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class DecodedBinlog:
    events: tuple[BinlogEvent, ...]
    markers: tuple[TransactionMarker, ...]


@dataclass(frozen=True, slots=True)
class NormalizedEvidence:
    schemas: tuple[Schema, ...]
    physical_records: tuple[PhysicalRecord, ...]
    events: tuple[BinlogEvent, ...]
    markers: tuple[TransactionMarker, ...]


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    case_id: str
    operation: str
    completed_at: datetime
    item_count: int


@dataclass(frozen=True, slots=True)
class RawOutputReference:
    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _required(self.path, "raw-output path"))
        object.__setattr__(self, "sha256", _sha256(self.sha256))
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")


class ToolRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolRun:
    id: str
    case_id: str
    evidence_id: str
    tool_name: str
    tool_version: str
    executable_path: str
    executable_sha256: str
    arguments: tuple[str, ...]
    started_at: datetime
    status: ToolRunStatus = ToolRunStatus.RUNNING
    finished_at: datetime | None = None
    exit_code: int | None = None
    stdout: RawOutputReference | None = None
    stderr: RawOutputReference | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "tool run id"),
            (self.case_id, "case id"),
            (self.evidence_id, "evidence id"),
            (self.tool_name, "tool name"),
            (self.tool_version, "tool version"),
            (self.executable_path, "executable path"),
        ):
            _required(value, label)
        object.__setattr__(self, "executable_sha256", _sha256(self.executable_sha256))
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        if self.finished_at is not None and self.finished_at.tzinfo is None:
            raise ValueError("finished_at must be timezone-aware")
        if self.status is ToolRunStatus.RUNNING:
            if self.finished_at is not None or self.exit_code is not None:
                raise ValueError("running tool execution cannot have completion details")
        elif self.finished_at is None or self.exit_code is None:
            raise ValueError("completed tool execution requires time and exit code")


@dataclass(frozen=True, slots=True)
class StartToolRunRequest:
    case_id: str
    evidence_id: str
    tool_name: str
    tool_version: str
    executable_path: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompleteToolRunRequest:
    run_id: str
    exit_code: int
    stdout: bytes
    stderr: bytes
