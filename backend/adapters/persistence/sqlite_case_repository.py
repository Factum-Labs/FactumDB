"""SQLite implementation of the case repository.

Satisfies two contracts on purpose. CaseRepositoryPort (an ABC) is the one
this class inherits from; CaseRepository in
core/application/ports/workflow_repositories.py is a Protocol that the
application's use cases depend on, and this class satisfies it structurally
by having get() as well as find_by_id().

The two were written separately and have not been reconciled yet - see the
note in docs/sqlite-schema.md. Implementing both keeps the use cases working
while that is agreed.

Column names stay case_id and case_name rather than following the model's id
and name, because a bare "id" is ambiguous once several tables are joined.
The mapping happens here, which is what this layer is for.
"""

from typing import Optional

from adapters.persistence._timestamps import from_text, to_text
from core.application.ports.case_repository_port import CaseRepositoryPort
from core.domain.models.case import Case

_COLUMNS = "case_id, case_name, examiner, workspace_path, created_at"


class SqliteCaseRepository(CaseRepositoryPort):
    """Stores cases in the SQLite case database."""

    def __init__(self, connection):
        """Takes an open connection rather than a path, so every repository in
        a case shares one, and a test can pass ':memory:'."""
        self._connection = connection

    def save(self, case: Case) -> None:
        """Write a case, replacing it if the id is already there.

        Replacing rather than failing means re-running the pipeline on the
        same case does not crash. The row is case metadata, not evidence.
        """
        self._connection.execute(
            f"INSERT OR REPLACE INTO cases ({_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
            (
                case.id,
                case.name,
                case.examiner,
                case.workspace_path,
                to_text(case.created_at),
            ),
        )
        self._connection.commit()

    def find_by_id(self, case_id: str) -> Optional[Case]:
        """Return the case with this id, or None if there is not one.

        None rather than an exception, because "we do not have that case" is
        a normal answer to a lookup.
        """
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        return _row_to_case(row) if row is not None else None

    def get(self, case_id: str) -> Optional[Case]:
        """Same lookup under the name the application's use cases call."""
        return self.find_by_id(case_id)


def _row_to_case(row) -> Case:
    return Case(
        row["case_id"],
        row["case_name"],
        row["examiner"],
        from_text(row["created_at"]),
        row["workspace_path"],
    )
