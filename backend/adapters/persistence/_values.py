"""Storing a row's values as JSON without losing what they are.

A row is a mapping of column name to Value, and Value is wider than JSON:

    int | str | Decimal | datetime | bool | None | UndecodableValue | Unobserved

Four of those have no JSON equivalent, so they are written as small tagged
objects and read straight back. The tags are safe because MySQL column values
are always scalars - a number, a string, a date, NULL. They are never
dictionaries, so a dict appearing where a value belongs can only be one of
these markers and can never collide with real data. That is decision D in
docs/canonical-model.md.

The one that matters most is Decimal.

    json.dumps(Decimal("4000.10"))     would need a float
    float(Decimal("4000.10"))          is 4000.099999999999...

JSON numbers are IEEE-754 doubles, and a double cannot hold every decimal
exactly. Writing a balance as a float would quietly change it, and the tool
would then report a number the database never held. Decimals are stored as
their exact text instead and rebuilt with Decimal(), so 4000.10 stays
4000.10.
"""

import json
from datetime import datetime
from decimal import Decimal

from core.domain.models.values import UNOBSERVED, UndecodableValue, Unobserved

_DECIMAL = "__decimal__"
_DATETIME = "__datetime__"
_UNDECODABLE = "__undecodable__"
_UNOBSERVED = "__unobserved__"


def to_json(values) -> str:
    """A row's values -> the text stored in a *_json column."""
    return json.dumps({name: _encode(value) for name, value in values.items()})


def from_json(text: str) -> dict:
    """The stored text -> the row's values, with the types restored."""
    return {name: _decode(value) for name, value in json.loads(text).items()}


def _encode(value):
    if value is None or isinstance(value, (bool, int, str)):
        # bool is checked before int on purpose: in Python True is an int, and
        # JSON keeps them apart, so listing bool first preserves the type.
        return value
    if isinstance(value, Decimal):
        return {_DECIMAL: str(value)}
    if isinstance(value, datetime):
        return {_DATETIME: value.isoformat()}
    if isinstance(value, UndecodableValue):
        return {_UNDECODABLE: value.reason}
    if isinstance(value, Unobserved):
        return {_UNOBSERVED: True}
    raise TypeError(f"cannot store a value of type {type(value).__name__}")


def _decode(value):
    if not isinstance(value, dict):
        return value
    if _DECIMAL in value:
        return Decimal(value[_DECIMAL])
    if _DATETIME in value:
        return datetime.fromisoformat(value[_DATETIME])
    if _UNDECODABLE in value:
        return UndecodableValue(value[_UNDECODABLE])
    if _UNOBSERVED in value:
        return UNOBSERVED
    raise ValueError(f"unrecognised stored value: {value!r}")
