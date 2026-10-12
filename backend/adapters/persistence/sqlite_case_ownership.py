"""Catalog-only case ownership. Unknown legacy owners remain inaccessible."""

from core.application.errors import NotFoundError


class SqliteCaseOwnership:
    def __init__(self, connection):
        self.connection = connection
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS case_owners (
                case_id TEXT PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_case_owners_user ON case_owners(user_id);
        """)
        # Seal legacy rows once, including unknown owners. Later sign-ups
        # must not acquire historical cases by choosing an examiner name.
        with connection:
            connection.execute("""
                INSERT OR IGNORE INTO case_owners(case_id, user_id)
                SELECT c.case_id, u.user_id FROM cases c
                LEFT JOIN users u ON u.username_key = lower(c.examiner)
            """)

    def assign(self, case_id, user_id):
        with self.connection:
            self.connection.execute(
                "INSERT INTO case_owners(case_id, user_id) VALUES (?, ?)", (case_id, user_id),
            )

    def require_owner(self, case_id, user_id):
        if not self.connection.execute(
            "SELECT 1 FROM case_owners WHERE case_id = ? AND user_id = ?", (case_id, user_id),
        ).fetchone():
            raise NotFoundError("The requested case or resource was not found.")

    def case_ids(self, user_id):
        return [row[0] for row in self.connection.execute("""
            SELECT c.case_id FROM cases c JOIN case_owners o USING(case_id)
            WHERE o.user_id = ? ORDER BY c.created_at DESC
        """, (user_id,))]

    def require_exclusive_workspace(self, user_id):
        if (self.connection.execute("SELECT count(*) FROM users").fetchone()[0] != 1
                or self.connection.execute("""
                    SELECT 1 FROM cases c LEFT JOIN case_owners o USING(case_id)
                    WHERE o.user_id IS NULL OR o.user_id != ? LIMIT 1
                """, (user_id,)).fetchone()):
            raise PermissionError(
                "Whole-workspace operations are unavailable in a shared workspace."
            )
