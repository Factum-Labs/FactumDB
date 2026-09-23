from __future__ import annotations

import re
from pathlib import Path


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def safe_component(value: str, label: str) -> str:
    if value in {".", ".."} or _SAFE_COMPONENT.fullmatch(value) is None:
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def contained(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"path escapes configured workspace root: {candidate}") from error
    return resolved
