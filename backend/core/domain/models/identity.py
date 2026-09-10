"""Record identity: turning primary key values into a stable, sortable handle.

The rendered forms here are a contract with the frontend (`RecordRef` in
`frontend/src/data/types.ts`), so the shapes are fixed:

    id     "accounts:101"            stable handle, short table name
    table  "finance.accounts"        fully qualified
    key    "account_id = 101"        human rendering of the key
    pk     "101"                     the key value alone, the canonical sort key
    label  "finance.accounts · 101"  what a table row or graph node shows

`database` is carried in addition to the frontend's five fields. The id uses the
short table name, so two databases in one case contributing the same table name
produce colliding ids; keeping the database lets the services detect that and
report R-ID-003 rather than silently merging two different records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.models.values import UNOBSERVED, UndecodableValue, Value

#: Separator between components of a composite key, e.g. "order_lines:5001|2".
KEY_SEPARATOR = "|"


class UnrenderableKey(Exception):
    """A key value has no defensible textual rendering.

    Raised rather than returned because a record with no renderable identity
    cannot be constructed at all - the caller must turn this into a finding and
    correlate the event to nothing.
    """

    def __init__(self, column: str, reason: str) -> None:
        super().__init__(f"{column}: {reason}")
        self.column = column
        self.reason = reason


def render_key_value(column: str, value: Value) -> str:
    """Render one primary key component (R-ID-001).

    Deliberately narrow. A primary key is the thing every downstream conclusion
    hangs off, so anything we cannot render exactly is refused rather than
    approximated.
    """
    if value is UNOBSERVED:
        raise UnrenderableKey(column, "key column not present in the row image")
    if isinstance(value, UndecodableValue):
        raise UnrenderableKey(column, value.reason)
    if value is None:
        # SQL forbids NULL in a primary key, so this means the image is wrong or
        # the column was misidentified as part of the key. Either way, guessing
        # an identity from it would be fabrication.
        raise UnrenderableKey(column, "key column is NULL")
    if isinstance(value, bool):
        raise UnrenderableKey(column, "boolean is not a usable key rendering")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value
    raise UnrenderableKey(column, f"unsupported key type {type(value).__name__}")


@dataclass(frozen=True, slots=True, order=True)
class RecordKey:
    """A hashable, comparable primary key. Used to index records internally."""

    database: str
    table: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @property
    def qualified_table(self) -> str:
        return f"{self.database}.{self.table}"

    @property
    def pk(self) -> str:
        return KEY_SEPARATOR.join(self.values)

    @property
    def record_id(self) -> str:
        return f"{self.table}:{self.pk}"

    @property
    def has_separator_collision(self) -> bool:
        """True when a key value itself contains the composite separator.

        The ambiguity is real - "a|b" as one value and ("a", "b") as two produce
        the same pk string - so it is surfaced as R-ID-002 rather than escaped
        away. Escaping would hide a genuine reason to distrust the identity.
        """
        return any(KEY_SEPARATOR in v for v in self.values)


@dataclass(frozen=True, slots=True)
class RecordRef:
    """A record identity as the report and the UI see it."""

    id: str
    table: str
    key: str
    pk: str
    label: str
    database: str
    key_columns: tuple[str, ...]
    key_values: tuple[str, ...]

    @classmethod
    def from_key(cls, key: RecordKey) -> RecordRef:
        rendered = ", ".join(f"{c} = {v}" for c, v in zip(key.columns, key.values, strict=True))
        return cls(
            id=key.record_id,
            table=key.qualified_table,
            key=rendered,
            pk=key.pk,
            label=f"{key.qualified_table} · {key.pk}",
            database=key.database,
            key_columns=key.columns,
            key_values=key.values,
        )

    def to_key(self) -> RecordKey:
        return RecordKey(
            database=self.database,
            table=self.table.split(".", 1)[-1],
            columns=self.key_columns,
            values=self.key_values,
        )
