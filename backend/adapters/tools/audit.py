"""Audited subprocess execution for forensic extraction utilities."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence

from core.application.models import CompleteToolRunRequest, StartToolRunRequest
from core.application.use_cases.audit import ToolRunAuditService


class AuditedSubprocessRunner:
    """Record one ToolRun for every subprocess invocation."""

    def __init__(
        self,
        audit: ToolRunAuditService,
        case_id: str,
        evidence_id: str,
        *,
        versions: dict[str, str] | None = None,
    ) -> None:
        self._audit = audit
        self._case_id = case_id
        self._evidence_id = evidence_id
        self._versions = versions or {}
        self.run_ids: list[str] = []

    def run(self, command: Sequence[str], *, capture_output: bool = True):
        if not command:
            raise ValueError("tool command must not be empty")
        requested = str(command[0])
        executable = shutil.which(requested) or requested
        tool_name = _tool_name(requested)
        recorded_executable = executable
        recorded_arguments = tuple(str(value) for value in command[1:])
        if tool_name == "ibd2sql" and recorded_arguments:
            # ibd2sql is a Python script run by an interpreter. The script is
            # what identifies the tool: hashing python3 would record which
            # Python ran, not which ibd2sql produced the rows.
            recorded_executable = recorded_arguments[0]
            recorded_arguments = recorded_arguments[1:]
        started = self._audit.start(StartToolRunRequest(
            case_id=self._case_id,
            evidence_id=self._evidence_id,
            tool_name=tool_name,
            tool_version=self._versions.get(tool_name, "unknown"),
            executable_path=recorded_executable,
            arguments=recorded_arguments,
        ))
        self.run_ids.append(started.id)
        executed_command = [executable, *(str(value) for value in command[1:])]
        try:
            completed = subprocess.run(executed_command, capture_output=capture_output)
        except OSError as error:
            self._audit.complete(CompleteToolRunRequest(
                started.id, 127, b"", str(error).encode(errors="replace"),
            ))
            raise
        self._audit.complete(CompleteToolRunRequest(
            started.id,
            completed.returncode,
            completed.stdout or b"",
            completed.stderr or b"",
        ))
        return completed


def _tool_name(executable: str) -> str:
    name = executable.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.startswith("python"):
        return "ibd2sql"
    if name.endswith(".exe"):
        name = name[:-4]
    return name
