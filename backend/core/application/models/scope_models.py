"""Which databases and tables an investigation looks at."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceScope:
    """The part of the evidence the analysis covers.

    The scope decides what the analysis looks at, never what is kept. Every
    extracted row and event stays stored whatever the scope, so narrowing it
    can always be undone and nothing is lost by trying a narrow scope first.

    An empty scope means everything. A name in `databases` brings in every
    table of that database; `tables` adds single (database, table) pairs.
    Names are compared exactly, because MySQL on Linux treats table names as
    case sensitive.
    """

    databases: frozenset[str] = frozenset()
    tables: frozenset[tuple[str, str]] = frozenset()

    @property
    def is_everything(self) -> bool:
        return not self.databases and not self.tables

    def includes(self, database: str, table: str) -> bool:
        return (
            self.is_everything
            or database in self.databases
            or (database, table) in self.tables
        )
