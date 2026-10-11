"""Rebuildable, indexed desktop history summaries."""
import json


class HistorySummaries:
    def __init__(self, connection):
        self.connection = connection

    def rebuild(self, case_id):
        c = self.connection
        c.execute("DELETE FROM history_summaries WHERE case_id = ?", (case_id,))
        c.execute("DELETE FROM history_summary_ready WHERE case_id = ?", (case_id,))
        c.execute("""INSERT INTO history_summaries
            SELECT a.case_id, CAST(j.key AS INTEGER),
                json_extract(j.value, '$.record.database'),
                json_extract(j.value, '$.record.table'),
                json_extract(j.value, '$.record.id'),
                json_extract(j.value, '$.record'),
                json_extract(j.value, '$.method'),
                json_array_length(j.value, '$.steps')
            FROM analysis_results a, json_each(a.result_json, '$.histories') j
            WHERE a.case_id = ? AND a.stage = 'reconstruction'""", (case_id,))
        c.execute("INSERT INTO history_summary_ready VALUES (?)", (case_id,))

    def ensure(self, case_id):
        if not self.connection.execute("SELECT 1 FROM history_summary_ready WHERE case_id = ?", (case_id,)).fetchone():
            self.connection.execute("SAVEPOINT history_backfill")
            try:
                self.rebuild(case_id)
            except BaseException:
                self.connection.execute("ROLLBACK TO history_backfill")
                raise
            finally:
                self.connection.execute("RELEASE history_backfill")

    def tables(self, case_id):
        self.ensure(case_id)
        rows = self.connection.execute("""SELECT database_name, qualified_table_name, count(*)
            FROM history_summaries WHERE case_id = ?
            GROUP BY database_name, qualified_table_name ORDER BY qualified_table_name""", (case_id,))
        tables = [dict(database=r[0], table=r[1], count=r[2]) for r in rows]
        return {"tables": tables, "total": sum(r['count'] for r in tables)}

    def page(self, case_id, database=None, table=None, offset=0, limit=100, include_details=False):
        if type(include_details) is not bool:
            raise ValueError("include_details must be a boolean")
        if (database is None) != (table is None):
            raise ValueError("database and table must be supplied together")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative and limit must be 1–100")
        if database is not None and (not isinstance(database, str) or not isinstance(table, str)):
            raise ValueError("database and table must be strings")
        self.connection.execute("SAVEPOINT history_page")
        try:
            self.ensure(case_id)
            return self._page(case_id, database, table, offset, limit, include_details)
        except BaseException:
            self.connection.execute("ROLLBACK TO history_page")
            raise
        finally:
            self.connection.execute("RELEASE history_page")

    def _page(self, case_id, database, table, offset, limit, include_details):
        where, args = "case_id = ?", [case_id]
        if table is not None:
            where += " AND database_name = ? AND qualified_table_name = ?"
            args += [database, table]
        total = self.connection.execute(f"SELECT count(*) FROM history_summaries WHERE {where}", args).fetchone()[0]
        result = self.connection.execute(f"SELECT record_json, method, step_count, ordinal FROM history_summaries WHERE {where} ORDER BY ordinal LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        items = [dict(record=json.loads(r[0]), method=r[1], step_count=r[2]) for r in result]
        if include_details and result:
            ordinals = [r[3] for r in result]
            placeholders = ','.join('?' for _ in ordinals)
            histories = {int(r[0]): json.loads(r[1]) for r in self.connection.execute(
                "SELECT j.key, j.value FROM analysis_results a, json_each(a.result_json, '$.histories') j "
                f"WHERE a.case_id = ? AND a.stage = 'reconstruction' AND CAST(j.key AS INTEGER) IN ({placeholders})",
                [case_id, *ordinals])}
            from sidecar.views import history_details
            details = history_details(self.connection, case_id, [histories[o] for o in ordinals])
            items = [dict(summary=summary, **detail) for summary, detail in zip(items, details)]
        return dict(items=items, total=total, offset=offset, limit=limit)

    def locate(self, case_id, identity, qualified_table=None):
        self.ensure(case_id)
        matches = self.connection.execute("""SELECT ordinal, database_name, qualified_table_name
            FROM history_summaries WHERE case_id = ? AND record_id = ?
            AND (? IS NULL OR qualified_table_name = ?)""", (case_id, identity, qualified_table, qualified_table)).fetchall()
        if len(matches) != 1:
            raise ValueError("Record identity is ambiguous" if matches else "Record history not found")
        ordinal, database, table = matches[0]
        index = self.connection.execute("SELECT count(*) FROM history_summaries WHERE case_id = ? AND database_name = ? AND qualified_table_name = ? AND ordinal < ?", (case_id, database, table, ordinal)).fetchone()[0]
        return dict(database=database, table=table, offset=(index // 100) * 100)
