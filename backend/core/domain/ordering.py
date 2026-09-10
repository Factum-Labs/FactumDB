"""Canonical ordering. Everything the engine emits is sorted with these.

Determinism is a forensic requirement, not a nicety: the same evidence has to
produce byte-identical output on any machine, so nothing here may depend on
locale, hash seed, or input order.

These comparators are written against the canonical model rather than ported
from `frontend/src/lib/correlation.ts`, which predates it. Three corrections:

* Transactions sort on `start_position`, not on the position of the COMMIT. A
  rolled-back or incomplete transaction has no COMMIT, so a commit-based sort key
  is undefined for exactly the cases that matter most.

* Binlog files sort by their position in `BinlogInventory.listed_files` - the
  server's own record of its log sequence - falling back to lexical order only
  when there is no inventory. Plain lexical ordering silently breaks the moment a
  case contains logs written under two different basenames.

* Key components compare numerically only when they are strict digit strings, and
  composite keys compare component-wise. The frontend's `Number()` coercion loses
  precision above 2^53, accepts "0x10" as 16, and sorts "1|10" before "1|9".
"""

from __future__ import annotations

from core.domain.models.canonical import BinlogInventory
from core.domain.models.identity import KEY_SEPARATOR, RecordRef

__all__ = [
    "FileSequence",
    "basename",
    "cmp_key",
    "cmp_str",
    "event_sort_key",
    "record_sort_key",
    "transaction_sort_key",
]


def basename(path: str) -> str:
    """Last path component, splitting on both separators.

    Not `os.path.basename`: the domain must not import `os`, and more to the
    point, `os.path` splits according to the *host* platform. Evidence is
    acquired on Linux and may well be examined on Windows, so a host-dependent
    split would make the same case file compare differently on two machines.
    Binlog index entries are Linux absolute paths; we split on both separators so
    either form resolves the same way everywhere.
    """
    for separator in ("/", "\\"):
        path = path.rpartition(separator)[2]
    return path


def cmp_str(a: str, b: str) -> int:
    """Plain codepoint comparison.

    Deliberately not `locale.strcoll` or any collation-aware comparison, whose
    result depends on the host's locale data. The output must be identical on the
    examiner's machine and on the reviewer's.
    """
    return -1 if a < b else (1 if a > b else 0)


def _component_sort_key(component: str) -> tuple[int, int, str]:
    """Sort key for one key component: digit strings numerically, else lexically.

    The strictness is the point. `str.isdigit()` accepts only ASCII digits here
    because the component came from `render_key_value`, so anything else is a
    string key that happens to look numeric and must keep its literal ordering.
    Python ints are arbitrary precision, so BIGINT keys beyond 2^53 order
    correctly.
    """
    if component.isascii() and component.isdigit():
        return (0, int(component), "")
    if component.startswith("-") and component[1:].isascii() and component[1:].isdigit():
        return (0, int(component), "")
    return (1, 0, component)


def cmp_key(a: str, b: str) -> int:
    """Compare two rendered primary keys, component-wise across the separator."""
    ka = [_component_sort_key(p) for p in a.split(KEY_SEPARATOR)]
    kb = [_component_sort_key(p) for p in b.split(KEY_SEPARATOR)]
    return -1 if ka < kb else (1 if ka > kb else 0)


class FileSequence:
    """Orders binlog files by the server's own sequence.

    `mysql-bin.index` stores absolute paths while our working copies live in the
    case folder, so every lookup here is by basename. A file the inventory does
    not list still has to sort somewhere; it goes after every listed file, in
    lexical order, and the caller is expected to report R-COV-001 once so the
    fallback is visible in the report rather than assumed.
    """

    __slots__ = ("_has_inventory", "_index", "_unlisted")

    def __init__(self, inventory: BinlogInventory | None) -> None:
        self._has_inventory = inventory is not None
        self._index: dict[str, int] = {}
        self._unlisted: set[str] = set()
        if inventory is not None:
            for position, path in enumerate(inventory.listed_files):
                self._index.setdefault(basename(path), position)

    def index(self, source_file: str) -> int:
        """Position of `source_file` in the server's log sequence."""
        name = basename(source_file)
        found = self._index.get(name)
        if found is None:
            self._unlisted.add(name)
            return len(self._index)
        return found

    def sort_key(self, source_file: str) -> tuple[int, str]:
        """Index first, then name - so unlisted files stay mutually ordered."""
        name = basename(source_file)
        return (self.index(source_file), name)

    @property
    def used_fallback(self) -> bool:
        """True once any file had to be ordered without inventory backing."""
        return not self._has_inventory or bool(self._unlisted)

    @property
    def unlisted_files(self) -> tuple[str, ...]:
        return tuple(sorted(self._unlisted))


def transaction_sort_key(
    sequence: FileSequence, source_file: str, start_position: int, transaction_id: str
) -> tuple[tuple[int, str], int, str]:
    """Canonical transaction order: log sequence, then BEGIN position, then id."""
    return (sequence.sort_key(source_file), start_position, transaction_id)


def event_sort_key(
    sequence: FileSequence, source_file: str, log_position: int
) -> tuple[tuple[int, str], int]:
    """Canonical event order: log sequence, then position within the file.

    This is the engine's only total order over events. Timestamps are not used:
    `mysqlbinlog` prints one-second resolution converted from server-local time,
    so events inside a single transaction routinely share one.
    """
    return (sequence.sort_key(source_file), log_position)


def record_sort_key(record: RecordRef) -> tuple[str, list[tuple[int, int, str]], str]:
    """Canonical record order: qualified table, then primary key, then id."""
    return (
        record.table,
        [_component_sort_key(p) for p in record.pk.split(KEY_SEPARATOR)],
        record.id,
    )
