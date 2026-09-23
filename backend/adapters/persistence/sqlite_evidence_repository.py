"""SQLite implementation of EvidenceRepositoryPort.

Stores the files that were seized for a case, along with both hashes. Storing
the hash of the original and the hash of the working copy is the point: if the
two ever differ, the working copy is not a faithful reproduction and nothing
extracted from it can be relied on.

EvidenceFile keeps its timestamp as an ISO-8601 string rather than a datetime,
so there is no conversion to do here - the column stores it as written.
"""

from typing import Optional, Sequence

from core.application.ports.evidence_repository_port import EvidenceRepositoryPort
from core.domain.models.evidence import EvidenceFile

_COLUMNS = """
    evidence_id, case_id, evidence_type, file_name, original_path,
    size_bytes, sha256_original, working_copy_path, sha256_working,
    registered_at, acquisition_method
"""


class SqliteEvidenceRepository(EvidenceRepositoryPort):
    """Stores registered evidence files in the SQLite case database."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, evidence: EvidenceFile) -> None:
        self._connection.execute(
            f"INSERT OR REPLACE INTO evidence_files ({_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence.evidence_id,
                evidence.case_id,
                evidence.evidence_type,
                evidence.file_name,
                evidence.original_path,
                evidence.size_bytes,
                evidence.sha256_original,
                evidence.working_copy_path,
                evidence.sha256_working,
                evidence.registered_at,
                evidence.acquisition_method,
            ),
        )
        self._connection.commit()

    def find_by_id(self, evidence_id: str) -> Optional[EvidenceFile]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        return _row_to_evidence(row) if row is not None else None

    def list_by_case(self, case_id: str) -> Sequence[EvidenceFile]:
        """Ordered by file name so the same case always lists in the same
        order. Without an ORDER BY, SQLite may return rows in any order, and a
        report that lists evidence differently on each run looks unreliable."""
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files WHERE case_id = ? ORDER BY file_name",
            (case_id,),
        ).fetchall()
        return [_row_to_evidence(r) for r in rows]

    def list_by_type(self, case_id: str, evidence_type: str) -> Sequence[EvidenceFile]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM evidence_files "
            "WHERE case_id = ? AND evidence_type = ? ORDER BY file_name",
            (case_id, evidence_type),
        ).fetchall()
        return [_row_to_evidence(r) for r in rows]


def _row_to_evidence(row) -> EvidenceFile:
    return EvidenceFile(
        evidence_id=row["evidence_id"],
        case_id=row["case_id"],
        evidence_type=row["evidence_type"],
        file_name=row["file_name"],
        original_path=row["original_path"],
        size_bytes=row["size_bytes"],
        sha256_original=row["sha256_original"],
        working_copy_path=row["working_copy_path"],
        sha256_working=row["sha256_working"],
        registered_at=row["registered_at"],
        acquisition_method=row["acquisition_method"],
    )
