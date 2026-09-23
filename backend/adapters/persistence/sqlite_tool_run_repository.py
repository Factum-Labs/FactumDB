"""SQLite implementation of the tool run repository.

This is the provenance spine. Every table holding extracted data stores a
tool_run_id, so any value that reaches a report can be traced back to the
exact invocation behind it.

What a row records is deliberately more than "which tool ran":

  executable_path and executable_sha256 identify the binary itself, so the
  claim is about one specific build rather than a version string that
  several builds could share.

  arguments is stored as a JSON array rather than one command string,
  because re-joining arguments into a line loses the boundaries between them
  as soon as a path contains a space.

  stdout and stderr are both kept, each with its own hash and size. Both
  matter - innochecksum reports a damaged page on stderr, so storing only
  stdout would record an empty success for a file it had just called
  invalid.

Implements ToolRunRepositoryPort (ABC) and also satisfies the
ToolRunRepository Protocol the use cases depend on, hence get() alongside
find_by_id().
"""

import json
from typing import Optional, Sequence

from adapters.persistence._timestamps import from_text, to_text
from core.application.ports.tool_run_repository_port import ToolRunRepositoryPort
from core.domain.models.canonical import EventRef, ProvenanceReference
from core.domain.models.evidence import RawOutputReference, ToolRun, ToolRunStatus

_COLUMNS = """
    tool_run_id, case_id, evidence_id, tool_name, tool_version,
    executable_path, executable_sha256, arguments_json, status,
    started_at, finished_at, exit_code,
    stdout_path, stdout_sha256, stdout_size_bytes,
    stderr_path, stderr_sha256, stderr_size_bytes
"""


class SqliteToolRunRepository(ToolRunRepositoryPort):
    """Stores one row per external tool invocation."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, run: ToolRun) -> None:
        self._connection.execute(
            f"INSERT OR REPLACE INTO tool_runs ({_COLUMNS}) "
            "VALUES (" + ", ".join(["?"] * 18) + ")",
            (
                run.id,
                run.case_id,
                run.evidence_id,
                run.tool_name,
                run.tool_version,
                run.executable_path,
                run.executable_sha256,
                json.dumps(list(run.arguments)),
                str(run.status),
                to_text(run.started_at),
                to_text(run.finished_at) if run.finished_at is not None else None,
                run.exit_code,
                *_output_columns(run.stdout),
                *_output_columns(run.stderr),
            ),
        )
        self._connection.commit()

    def find_by_id(self, tool_run_id: str) -> Optional[ToolRun]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM tool_runs WHERE tool_run_id = ?",
            (tool_run_id,),
        ).fetchone()
        return _row_to_tool_run(row) if row is not None else None

    def get(self, run_id: str) -> Optional[ToolRun]:
        """Same lookup under the name the use cases call."""
        return self.find_by_id(run_id)

    def list_by_evidence(self, evidence_id: str) -> Sequence[ToolRun]:
        """Oldest first, so the list reads as the order things were done in.

        This is what an evidence file's detail view shows: which tools have
        been run against it and whether each one succeeded.
        """
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM tool_runs WHERE evidence_id = ? "
            "ORDER BY started_at, tool_run_id",
            (evidence_id,),
        ).fetchall()
        return [_row_to_tool_run(r) for r in rows]

    def provenance_for(self, ref: EventRef) -> Optional[ProvenanceReference]:
        """Which tool run produced the event at this position.

        Part of the domain layer's EvidenceContext protocol. EventRef is
        (source_file, log_position), and there is no direct key from that to a
        tool run, so the lookup joins through binlog_events, which stores both
        the position and the run that produced it.

        Returns None when nothing matches, which covers both "no such event"
        and "the event exists but no provenance was recorded". Either way
        there is nothing to show the examiner.
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


def _output_columns(output: Optional[RawOutputReference]):
    """A RawOutputReference flattened into its three columns, or three nulls."""
    if output is None:
        return (None, None, None)
    return (output.path, output.sha256, output.size_bytes)


def _read_output(row, prefix: str) -> Optional[RawOutputReference]:
    """Rebuild a RawOutputReference, or None if the stream was not captured."""
    path = row[f"{prefix}_path"]
    if path is None:
        return None
    return RawOutputReference(
        path=path,
        sha256=row[f"{prefix}_sha256"],
        size_bytes=row[f"{prefix}_size_bytes"],
    )


def _row_to_tool_run(row) -> ToolRun:
    finished = row["finished_at"]
    return ToolRun(
        id=row["tool_run_id"],
        case_id=row["case_id"],
        evidence_id=row["evidence_id"],
        tool_name=row["tool_name"],
        tool_version=row["tool_version"],
        executable_path=row["executable_path"],
        executable_sha256=row["executable_sha256"],
        arguments=tuple(json.loads(row["arguments_json"])),
        started_at=from_text(row["started_at"]),
        status=ToolRunStatus(row["status"]),
        finished_at=from_text(finished) if finished is not None else None,
        exit_code=row["exit_code"],
        stdout=_read_output(row, "stdout"),
        stderr=_read_output(row, "stderr"),
    )
