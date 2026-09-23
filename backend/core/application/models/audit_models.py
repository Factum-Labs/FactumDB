"""Application request, response and transfer contracts."""

from dataclasses import dataclass



@dataclass(frozen=True, slots=True)
class StartToolRunRequest:
    case_id: str
    evidence_id: str
    tool_name: str
    tool_version: str
    executable_path: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompleteToolRunRequest:
    run_id: str
    exit_code: int
    stdout: bytes
    stderr: bytes
