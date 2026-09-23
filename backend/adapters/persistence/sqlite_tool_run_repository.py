"""SQLite implementation of ToolRunRepositoryPort.

This is the provenance spine. Every other table that holds extracted data
stores a tool_run_id, so any value in a report can be traced back to the exact
command that produced it, which version of the tool ran, whether it succeeded,
and the hash of the raw output it printed.

provenance_for() is also part of the domain layer's EvidenceContext protocol,
so the domain services can ask "where did this event come from" without
knowing anything about SQLite.
"""

from typing import Optional, Sequence

from core.application.ports.tool_run_repository_port import ToolRunRepositoryPort
from core.domain.models.canonical import EventRef, ProvenanceReference
from core.domain.models.evidence import ToolRun

_COLUMNS = """
    tool_run_id, evidence_id, tool_name, tool_version, command,
    started_at, finished_at, exit_code, raw_output_path, raw_output_sha256
"""


class SqliteToolRunRepository(ToolRunRepositoryPort):
    """Stores one row per external tool invocation."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, run: ToolRun) -> None:
        self._connection.execute(
            f"INSERT OR REPLACE INTO tool_runs ({_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.tool_run_id,
                run.evidence_id,
                run.tool_name,
                run.tool_version,
                run.command,
                run.started_at,
                run.finished_at,
                run.exit_code,
                run.raw_output_path,
                run.raw_output_sha256,
            ),
        )
        self._connection.commit()

    def find_by_id(self, tool_run_id: str) -> Optional[ToolRun]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM tool_runs WHERE tool_run_id = ?",
            (tool_run_id,),
        ).fetchone()
        return _row_to_tool_run(row) if row is not None else None

    def list_by_evidence(self, evidence_id: str) -> Sequence[ToolRun]:
        """Oldest first, so the list reads as the order things were done in."""
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM tool_runs WHERE evidence_id = ? "
            "ORDER BY started_at, tool_run_id",
            (evidence_id,),
        ).fetchall()
        return [_row_to_tool_run(r) for r in rows]

    def provenance_for(self, ref: EventRef) -> Optional[ProvenanceReference]:
        """Find the tool run behind one binlog event.

        EventRef is (source_file, log_position). There is no direct key from
        that to a tool run, so the lookup goes through binlog_events, which
        stores both the position and the tool_run_id that produced it.

        Returns None when nothing matches. That covers both "no such event"
        and "the event exists but no provenance was recorded", which the port
        deliberately does not distinguish - either way there is nothing to
        show the examiner.
        """
        source_file, log_position = ref
        row = self._connection.execute(
            """
            SELECT t.tool_run_id, t.tool_name, t.evidence_id,
                   e.source_file, e.log_position
            FROM binlog_events e
            JOIN tool_runs t ON t.tool_run_id = e.tool_run_id
            WHERE e.source_file = ? AND e.log_position = ?
            """,
            (source_file, log_position),
        ).fetchone()

        if row is None:
            return None

        return ProvenanceReference(
            evidence_id=row["evidence_id"],
            tool_name=row["tool_name"],
            tool_run_id=row["tool_run_id"],
            source_file=row["source_file"],
            log_position=row["log_position"],
        )


def _row_to_tool_run(row) -> ToolRun:
    return ToolRun(
        tool_run_id=row["tool_run_id"],
        evidence_id=row["evidence_id"],
        tool_name=row["tool_name"],
        command=row["command"],
        started_at=row["started_at"],
        tool_version=row["tool_version"],
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        raw_output_path=row["raw_output_path"],
        raw_output_sha256=row["raw_output_sha256"],
    )
