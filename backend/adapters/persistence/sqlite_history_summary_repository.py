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
            with self.connection:
                self.rebuild(case_id)

    def tables(self, case_id):
        self.ensure(case_id)
        rows = self.connection.execute("""SELECT database_name, qualified_table_name, count(*)
            FROM history_summaries WHERE case_id = ?
            GROUP BY database_name, qualified_table_name ORDER BY qualified_table_name""", (case_id,))
        tables = [dict(database=r[0], table=r[1], count=r[2]) for r in rows]
        return {"tables": tables, "total": sum(r['count'] for r in tables)}

    def page(self, case_id, database=None, table=None, offset=0, limit=100):
        if (database is None) != (table is None):
            raise ValueError("database and table must be supplied together")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative and limit must be 1–100")
        if database is not None and (not isinstance(database, str) or not isinstance(table, str)):
            raise ValueError("database and table must be strings")
        self.ensure(case_id)
        where, args = "case_id = ?", [case_id]
        if table is not None:
            where += " AND database_name = ? AND qualified_table_name = ?"
            args += [database, table]
        total = self.connection.execute(f"SELECT count(*) FROM history_summaries WHERE {where}", args).fetchone()[0]
        result = self.connection.execute(f"SELECT record_json, method, step_count FROM history_summaries WHERE {where} ORDER BY ordinal LIMIT ? OFFSET ?", [*args, limit, offset])
        return dict(items=[dict(record=json.loads(r[0]), method=r[1], step_count=r[2]) for r in result], total=total, offset=offset, limit=limit)

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
