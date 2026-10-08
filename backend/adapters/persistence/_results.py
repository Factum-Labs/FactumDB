"""The domain's analysis results as JSON, and back again.

The four results the domain services produce - grouping, correlation,
reconstruction and reconciliation - are nested frozen dataclasses: tuples of
records, mappings of column values, enums, timestamps and findings. Each is
stored as one JSON document, and loading it has to give back an object equal
to the one that was saved. Otherwise a later stage would be working from
something slightly different from what the earlier stage produced.

Two rules make the round trip exact:

- Column values use the same tags as stored rows (see _values.py). A Value can
  be a str, a Decimal or a datetime, so "4000.10" on its own would not say
  which one it was.
- Everything else is rebuilt from the type hints of the dataclass it belongs
  to, so an enum comes back as that enum and a tuple as a tuple.

Anything this module does not know how to handle raises instead of being
guessed at. A change to the domain models then shows up as a failing test,
not as a result that quietly loads back different.
"""

import json
import types
import typing
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from functools import cache

from adapters.persistence._values import decode_value, encode_value
from core.domain.models.values import UndecodableValue, Unobserved, Value

_VALUE_TYPES = (Decimal, datetime, UndecodableValue, Unobserved)


def encode(obj):
    """A result object -> plain JSON data."""
    if isinstance(obj, _VALUE_TYPES):
        return encode_value(obj)
    if isinstance(obj, Enum):
        # Before str: the domain's enums are StrEnums, so they are strs too.
        return obj.value
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: encode(getattr(obj, f.name)) for f in fields(obj) if f.init}
    if isinstance(obj, Mapping):
        if not all(isinstance(key, str) for key in obj):
            raise TypeError("only mappings with str keys can be stored")
        return {key: encode(value) for key, value in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [encode(item) for item in obj]
    if isinstance(obj, (set, frozenset)):
        # Sorted, so the same set is always stored as the same text.
        return sorted((encode(item) for item in obj), key=json.dumps)
    raise TypeError(f"cannot store a {type(obj).__name__} in an analysis result")


def decode(data, hint):
    """Plain JSON data -> an object of the type `hint` describes."""
    alias_type = getattr(typing, "TypeAliasType", None)
    if alias_type is not None and isinstance(hint, alias_type):
        hint = hint.__value__
    if hint == Value:
        return decode_value(data)

    origin, args = typing.get_origin(hint), typing.get_args(hint)

    if origin in (typing.Union, types.UnionType):
        if data is None and type(None) in args:
            return None
        options = [arg for arg in args if arg is not type(None)]
        if len(options) != 1:
            raise TypeError(f"cannot tell which part of {hint} to rebuild")
        return decode(data, options[0])
    if origin is typing.Literal:
        if data not in args:
            raise ValueError(f"{data!r} is not one of {args}")
        return data
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(decode(item, args[0]) for item in data)
        if len(args) != len(data):
            raise ValueError(f"expected {len(args)} items for {hint}, found {len(data)}")
        return tuple(decode(item, arg) for item, arg in zip(data, args))
    if origin in (set, frozenset):
        return origin(decode(item, args[0]) for item in data)
    if origin in (Mapping, dict):
        return {key: decode(value, args[1]) for key, value in data.items()}

    if hint in _VALUE_TYPES:
        return decode_value(data)
    if isinstance(hint, type) and issubclass(hint, Enum):
        return hint(data)
    if hint in (str, int, bool):
        if type(data) is not hint:
            raise ValueError(f"expected {hint.__name__}, found {data!r}")
        return data
    if hint is type(None):
        return None
    if is_dataclass(hint):
        hints = _hints(hint)
        return hint(**{
            f.name: decode(data[f.name], hints[f.name]) for f in fields(hint) if f.init
        })
    raise TypeError(f"cannot rebuild a {hint!r}")


@cache
def _hints(cls):
    return typing.get_type_hints(cls)
