from __future__ import annotations

from collections.abc import Collection

from core.application.errors import NotFoundError, PrerequisiteError
from core.application.models import EvidenceFile, EvidenceKind, VerificationStatus
from core.application.ports import CaseRepository, EvidenceRepository


def require_case(cases: CaseRepository, case_id: str) -> None:
    if cases.get(case_id) is None:
        raise NotFoundError(f"case not found: {case_id}")


def require_verified_evidence(
    evidence_repository: EvidenceRepository,
    case_id: str,
    evidence_id: str,
    allowed_kinds: Collection[EvidenceKind],
) -> EvidenceFile:
    evidence = evidence_repository.get(case_id, evidence_id)
    if evidence is None:
        raise NotFoundError(f"evidence not found in case {case_id}: {evidence_id}")
    if evidence.kind not in allowed_kinds:
        expected = ", ".join(sorted(k.value for k in allowed_kinds))
        raise PrerequisiteError(
            f"evidence {evidence_id} has kind {evidence.kind.value}; expected {expected}"
        )
    if evidence.verification_status is not VerificationStatus.VERIFIED:
        raise PrerequisiteError(f"evidence is not verified: {evidence_id}")
    if not evidence.is_verified() or not evidence.working_copy_path.strip():
        raise PrerequisiteError(f"evidence has no matching verified working copy: {evidence_id}")
    return evidence
