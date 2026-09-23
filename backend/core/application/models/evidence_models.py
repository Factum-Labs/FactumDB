"""Application request, response and transfer contracts."""

from dataclasses import dataclass
from core.domain.models.evidence import EvidenceFile, EvidenceKind


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
