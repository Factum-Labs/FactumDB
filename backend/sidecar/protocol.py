from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import TextIO


JsonObject = dict[str, object]
CommandHandler = Callable[[Mapping[str, object]], object]


@dataclass(frozen=True, slots=True)
class SidecarRequest:
    request_id: str
    command: str
    payload: Mapping[str, object]

    @classmethod
    def from_json(cls, line: str) -> SidecarRequest:
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError("request must be a JSON object")
        request_id = decoded.get("request_id")
        command = decoded.get("command")
        payload = decoded.get("payload", {})
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        return cls(request_id.strip(), command.strip(), payload)


@dataclass(frozen=True, slots=True)
class SidecarResponse:
    request_id: str
    ok: bool
    result: object | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_json(self) -> str:
        value = asdict(self)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


class CommandRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, command: str, handler: CommandHandler) -> None:
        name = command.strip()
        if not name:
            raise ValueError("command must not be empty")
        if name in self._handlers:
            raise ValueError(f"command is already registered: {name}")
        self._handlers[name] = handler

    def dispatch(self, request: SidecarRequest) -> SidecarResponse:
        handler = self._handlers.get(request.command)
        if handler is None:
            return SidecarResponse(
                request.request_id,
                False,
                error_code="unknown_command",
                error_message=f"unknown command: {request.command}",
            )
        try:
            return SidecarResponse(request.request_id, True, result=handler(request.payload))
        except Exception as error:
            return SidecarResponse(
                request.request_id,
                False,
                error_code=type(error).__name__,
                error_message=str(error),
            )


def serve(input_stream: TextIO, output_stream: TextIO, router: CommandRouter) -> None:
    """Serve newline-delimited requests until stdin closes."""

    for line in input_stream:
        if not line.strip():
            continue
        request_id = "unknown"
        try:
            request = SidecarRequest.from_json(line)
            request_id = request.request_id
            response = router.dispatch(request)
        except Exception as error:
            response = SidecarResponse(
                request_id,
                False,
                error_code="invalid_request",
                error_message=str(error),
            )
        output_stream.write(response.to_json() + "\n")
        output_stream.flush()
