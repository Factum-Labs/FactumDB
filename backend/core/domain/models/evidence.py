"""Canonical evidence and tool audit models for application and persistence."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from core.domain.models._validation import _required, _sha256


class EvidenceKind(StrEnum):
    IBD = "ibd"
    BINLOG = "binlog"
    BINLOG_INDEX = "binlog_index"


class VerificationStatus(StrEnum):
    REGISTERED = "registered"
    VERIFIED = "verified"
    HASH_MISMATCH = "hash_mismatch"


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
    acquisition_method: str = ""

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
        if self.source_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] != self.filename:
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

    def is_verified(self) -> bool:
        return (
            self.verification_status is VerificationStatus.VERIFIED
            and self.working_copy_path is not None
            and self.source_sha256 == self.working_copy_sha256
        )

    @property
    def evidence_id(self) -> str:
        return self.id

    @property
    def evidence_type(self) -> str:
        return self.kind.value

    @property
    def file_name(self) -> str:
        return self.filename

    @property
    def original_path(self) -> str:
        return self.source_path

    @property
    def sha256_original(self) -> str:
        return self.source_sha256

    @property
    def sha256_working(self) -> str | None:
        return self.working_copy_sha256


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

    @property
    def tool_run_id(self) -> str:
        return self.id

    @property
    def command(self) -> str:
        """Display only; execute using the executable and argument tuple."""
        return shlex.join((self.executable_path, *self.arguments))

    @property
    def raw_output_path(self) -> str | None:
        return self.stdout.path if self.stdout else None

    @property
    def raw_output_sha256(self) -> str | None:
        return self.stdout.sha256 if self.stdout else None

    def succeeded(self) -> bool:
        return self.status is ToolRunStatus.SUCCEEDED and self.exit_code == 0
