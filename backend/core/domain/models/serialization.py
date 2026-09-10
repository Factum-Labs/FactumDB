"""Canonical JSON: the repeatability oracle.

Two runs over the same evidence must produce byte-identical output. That claim is
only testable if there is exactly one way to serialize a result, so this module
is it - the same function backs the repeatability tests, the golden snapshots and
the JSON report export.

Every choice here removes a degree of freedom: keys are sorted so dict insertion
order cannot leak in, separators are fixed so whitespace cannot vary, and the
three non-values get explicit markers so a reader can tell them apart.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from core.domain.models.values import UndecodableValue, Unobserved

#: Matches the SQLite persistence shape agreed in `docs/canonical-model.md`
#: decision 6. MySQL column values are always scalars, so a dict appearing where
#: a value belongs can only be one of these markers.
UNDECODABLE_MARKER = "__undecodable__"
UNOBSERVED_MARKER = "__unobserved__"


def to_jsonable(obj: Any) -> Any:
    """Recursively convert domain objects into JSON-safe primitives."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj

    if isinstance(obj, UndecodableValue):
        return {UNDECODABLE_MARKER: obj.reason}

    if isinstance(obj, Unobserved):
        return {UNOBSERVED_MARKER: True}

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, Decimal):
        # As text, never as float: a Decimal routed through a float would lose
        # exactly the precision that makes a balance comparison meaningful.
        return str(obj)

    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")

    if isinstance(obj, float):
        # Should never reach here - the domain refuses to compare floats - but if
        # one arrives it is marked rather than silently rounded into the output.
        return {UNDECODABLE_MARKER: f"binary float not serialized: {obj!r}"}

    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}

    if isinstance(obj, Mapping):
        return {str(k): to_jsonable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [to_jsonable(v) for v in obj]
        if isinstance(obj, (set, frozenset)):
            # Sets have no inherent order; sorting their rendered form is the
            # only way to keep output stable across hash seeds.
            items.sort(key=lambda v: json.dumps(v, sort_keys=True))
        return items

    raise TypeError(f"cannot serialize {type(obj).__name__} canonically")


def to_canonical_json(obj: Any) -> str:
    """One result, one string. Compare these to assert repeatability."""
    return json.dumps(
        to_jsonable(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def to_readable_json(obj: Any) -> str:
    """Same content, indented - for golden snapshots that get reviewed as diffs."""
    return json.dumps(to_jsonable(obj), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
