from __future__ import annotations

from core.application.errors import ConflictError, EvidenceIntegrityError, NotFoundError
from core.application.models import (
    EvidenceFile,
    RegisterEvidenceRequest,
    RegisterEvidenceResponse,
    VerificationStatus,
    VerifyEvidenceRequest,
    VerifyEvidenceResponse,
)
from core.application.ports import (
    CaseRepository,
    Clock,
    EvidenceInspector,
    EvidenceRepository,
    FileHasher,
    IdGenerator,
    WorkingCopyManager,
)


class RegisterEvidenceUseCase:
    """Inspect and hash source evidence without modifying it."""

    def __init__(
        self,
        cases: CaseRepository,
        evidence: EvidenceRepository,
        inspector: EvidenceInspector,
        hasher: FileHasher,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._cases = cases
        self._evidence = evidence
        self._inspector = inspector
        self._hasher = hasher
        self._ids = ids
        self._clock = clock

    def execute(self, request: RegisterEvidenceRequest) -> RegisterEvidenceResponse:
        if self._cases.get(request.case_id) is None:
            raise NotFoundError(f"case not found: {request.case_id}")
        metadata = self._inspector.inspect(request.source_path)
        if self._evidence.find_by_source(request.case_id, metadata.canonical_path) is not None:
            raise ConflictError(f"evidence is already registered: {metadata.canonical_path}")

        # Hash the canonical path returned by the inspector so path aliases cannot
        # register and hash two different files.
        digest = self._hasher.sha256(metadata.canonical_path)
        after_hash = self._inspector.inspect(metadata.canonical_path)
        if after_hash != metadata:
            raise EvidenceIntegrityError("source evidence changed while it was being hashed")
        registered = EvidenceFile(
            id=self._ids.new_id(),
            case_id=request.case_id,
            source_path=metadata.canonical_path,
            filename=metadata.filename,
            kind=metadata.kind,
            size_bytes=metadata.size_bytes,
            source_sha256=digest,
            registered_at=self._clock.now(),
        )
        self._evidence.save(registered)
        return RegisterEvidenceResponse(registered)


class VerifyEvidenceUseCase:
    """Create a working copy and prove that it is byte-identical by SHA-256."""

    def __init__(
        self,
        cases: CaseRepository,
        evidence: EvidenceRepository,
        copies: WorkingCopyManager,
        hasher: FileHasher,
    ) -> None:
        self._cases = cases
        self._evidence = evidence
        self._copies = copies
        self._hasher = hasher

    def execute(self, request: VerifyEvidenceRequest) -> VerifyEvidenceResponse:
        case = self._cases.get(request.case_id)
        if case is None:
            raise NotFoundError(f"case not found: {request.case_id}")
        evidence = self._evidence.get(request.case_id, request.evidence_id)
        if evidence is None:
            raise NotFoundError(
                f"evidence not found in case {request.case_id}: {request.evidence_id}"
            )
        if evidence.verification_status is VerificationStatus.VERIFIED:
            return VerifyEvidenceResponse(evidence)

        path: str | None = None
        try:
            path = self._copies.create(case, evidence)
            verified = evidence.with_verification(path, self._hasher.sha256(path))
            self._evidence.save(verified)
        except Exception:
            if path is not None:
                self._copies.discard(path)
            raise

        if verified.verification_status is VerificationStatus.HASH_MISMATCH:
            # Retain the mismatching copy and its digest as evidence of the failed
            # verification. Downstream use cases refuse to consume it.
            raise EvidenceIntegrityError(
                f"working-copy hash mismatch for evidence {request.evidence_id}"
            )
        return VerifyEvidenceResponse(verified)
