"""SQLite implementation of the evidence file repository.

Stores the files seized for a case and the hashes taken of them. Both hashes
matter: if the source hash and the working copy hash ever differ, the copy is
not a faithful reproduction and nothing extracted from it can be relied on.

The working copy columns are nullable because of when the row is written. A
file is registered and hashed first, and only then copied, so at registration
time there is no working copy to record. A null there is the honest answer,
and verification_status says which stage the file has reached.

Implements EvidenceRepositoryPort (ABC) and also satisfies the
EvidenceRepository Protocol the use cases depend on, which is why there are
both find_by_id/list_by_case and get/list_for_case.
"""

import json
from typing import Optional, Sequence

from adapters.persistence._timestamps import from_text, to_text
from core.application.ports.evidence_repository_port import EvidenceRepositoryPort
from core.domain.models.evidence import EvidenceFile, EvidenceKind, VerificationStatus

_COLUMNS = """
    evidence_id, case_id, kind, filename, source_path, size_bytes,
    source_sha256, verification_status, working_copy_path,
    working_copy_sha256, acquisition_method, registered_at
"""


class SqliteEvidenceRepository(EvidenceRepositoryPort):
    """Stores registered evidence files in the SQLite case database."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, evidence: EvidenceFile) -> None:
        self._connection.execute(
            f"INSERT OR REPLACE INTO evidence_files ({_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence.id,
                evidence.case_id,
                str(evidence.kind),
                evidence.filename,
                evidence.source_path,
                evidence.size_bytes,
                evidence.source_sha256,
                str(evidence.verification_status),
                evidence.working_copy_path,
                evidence.working_copy_sha256,
                evidence.acquisition_method,
                to_text(evidence.registered_at),
            ),
        )
        self._connection.commit()

    def find_by_id(self, evidence_id: str) -> Optional[EvidenceFile]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        return _row_to_evidence(row) if row is not None else None

    def get(self, case_id: str, evidence_id: str) -> Optional[EvidenceFile]:
        """Case-scoped lookup, which is what the use cases call.

        Scoping by case as well as by id means one case can never read another
        case's evidence through a guessed or stale id.
        """
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files "
            "WHERE case_id = ? AND evidence_id = ?",
            (case_id, evidence_id),
        ).fetchone()
        return _row_to_evidence(row) if row is not None else None

    def find_by_source(self, case_id: str, canonical_path: str) -> Optional[EvidenceFile]:
        """Has this file already been registered in this case?

        Registering the same file twice would give it two ids and two sets of
        tool runs, so the intake stage checks here first.
        """
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files "
            "WHERE case_id = ? AND source_path = ?",
            (case_id, canonical_path),
        ).fetchone()
        return _row_to_evidence(row) if row is not None else None

    def list_by_case(self, case_id: str) -> Sequence[EvidenceFile]:
        """Ordered by filename so a case always lists in the same order.

        Without an ORDER BY, SQLite may return rows in any order, and a report
        that lists evidence differently on each run looks unreliable.
        """
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files WHERE case_id = ? ORDER BY filename",
            (case_id,),
        ).fetchall()
        return [_row_to_evidence(r) for r in rows]

    def list_for_case(self, case_id: str) -> Sequence[EvidenceFile]:
        """Same listing under the name the use cases call."""
        return self.list_by_case(case_id)

    def list_by_type(self, case_id: str, evidence_type: str) -> Sequence[EvidenceFile]:
        """One kind only - "ibd", "binlog" or "binlog_index".

        The binlog decoding stage only wants the binlogs and the schema
        extraction stage only wants the .ibd files, so this saves both of them
        filtering the whole list.
        """
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files "
            "WHERE case_id = ? AND kind = ? ORDER BY filename",
            (case_id, str(evidence_type)),
        ).fetchall()
        return [_row_to_evidence(r) for r in rows]


def _row_to_evidence(row) -> EvidenceFile:
    return EvidenceFile(
        id=row["evidence_id"],
        case_id=row["case_id"],
        source_path=row["source_path"],
        filename=row["filename"],
        kind=EvidenceKind(row["kind"]),
        size_bytes=row["size_bytes"],
        source_sha256=row["source_sha256"],
        registered_at=from_text(row["registered_at"]),
        verification_status=VerificationStatus(row["verification_status"]),
        working_copy_path=row["working_copy_path"],
        working_copy_sha256=row["working_copy_sha256"],
        acquisition_method=row["acquisition_method"],
    )
