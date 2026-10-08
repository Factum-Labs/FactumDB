"""SQLite storage for report metadata: what was produced from a case, and when.

Every report or export written for a case gets a row: its format, a version
number, where it was written, and the SHA-256 and size of each file in it.

- Versions. A case is often reported on more than once - before and after more
  evidence arrives, or after the analysis is run again. Each format counts its
  own versions, so "the third JSON export of this case" means one thing.
- Checking a report later. The hashes say whether a file someone holds is the
  one FactumDB wrote. Anyone can check that with sha256sum, without having to
  trust the tool itself.

analysed_at is when the case's reconciliation result was saved, or empty if
the analysis had not run yet. A report made before the analysis was run again
then shows that it describes the older analysis.

This repository does not write report files. JSON and CSV exports record
themselves (case_export.py), and a PDF or HTML report can call record() the
same way once it is written.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from adapters.persistence._timestamps import from_text, to_text
from core.application.errors import NotFoundError

FORMATS = ("json", "csv", "html", "pdf")


@dataclass(frozen=True, slots=True)
class ReportFile:
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ReportRecord:
    report_id: str
    case_id: str
    format: str
    version: int
    location: str
    files: tuple[ReportFile, ...]
    analysed_at: Optional[datetime]
    created_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteReportRepository:
    """Records reports and exports made from a case."""

    def __init__(self, connection, *, now=_utc_now):
        self._connection = connection
        self._now = now

    def record(self, case_id: str, format: str, location, files) -> ReportRecord:
        """Record a finished report as the next version of its format.

        files are the paths written. They are hashed here, so call this only
        once they are complete.
        """
        if format not in FORMATS:
            raise ValueError(f"unknown report format: {format}")
        hashed = tuple(_hashed(Path(path)) for path in files)

        with self._connection:
            if self._connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone() is None:
                raise NotFoundError(f"case not found: {case_id}")
            version = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM reports "
                "WHERE case_id = ? AND format = ?",
                (case_id, format),
            ).fetchone()[0]
            analysed = self._connection.execute(
                "SELECT saved_at FROM analysis_results "
                "WHERE case_id = ? AND stage = 'reconciliation'",
                (case_id,),
            ).fetchone()
            record = ReportRecord(
                report_id=f"{case_id}:{format}:v{version}",
                case_id=case_id,
                format=format,
                version=version,
                location=str(location),
                files=hashed,
                analysed_at=from_text(analysed["saved_at"]) if analysed else None,
                created_at=self._now(),
            )
            self._connection.execute(
                """
                INSERT INTO reports (report_id, case_id, format, version, location,
                                     files_json, analysed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.report_id, case_id, format, version, record.location,
                    json.dumps([
                        {"name": f.name, "sha256": f.sha256, "size_bytes": f.size_bytes}
                        for f in hashed
                    ]),
                    analysed["saved_at"] if analysed else None,
                    to_text(record.created_at),
                ),
            )
        return record

    def list_by_case(self, case_id: str) -> Sequence[ReportRecord]:
        """Every report of the case, oldest first within each format."""
        rows = self._connection.execute(
            "SELECT * FROM reports WHERE case_id = ? ORDER BY format, version",
            (case_id,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def latest(self, case_id: str, format: str) -> Optional[ReportRecord]:
        row = self._connection.execute(
            "SELECT * FROM reports WHERE case_id = ? AND format = ? "
            "ORDER BY version DESC LIMIT 1",
            (case_id, format),
        ).fetchone()
        return _row_to_record(row) if row is not None else None


def _hashed(path: Path) -> ReportFile:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return ReportFile(path.name, digest.hexdigest(), path.stat().st_size)


def _row_to_record(row) -> ReportRecord:
    return ReportRecord(
        report_id=row["report_id"],
        case_id=row["case_id"],
        format=row["format"],
        version=row["version"],
        location=row["location"],
        files=tuple(ReportFile(**f) for f in json.loads(row["files_json"])),
        analysed_at=from_text(row["analysed_at"]) if row["analysed_at"] else None,
        created_at=from_text(row["created_at"]),
    )
