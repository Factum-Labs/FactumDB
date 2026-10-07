"""Durable orchestration state, separate from forensic analysis results."""

import json
from dataclasses import replace
from datetime import datetime, timezone

from adapters.persistence._results import decode, encode
from core.application.orchestration.models import PipelineRun, StageStatus


class SqlitePipelineRepository:
    def __init__(self, connection):
        self.connection = connection
        connection.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(case_id),
                run_json TEXT NOT NULL CHECK(json_valid(run_json)),
                created_at TEXT NOT NULL,
                obsolete INTEGER NOT NULL DEFAULT 0
            ) STRICT
        """)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(pipeline_runs)")}
        if "obsolete" not in columns:
            connection.execute("ALTER TABLE pipeline_runs ADD COLUMN obsolete INTEGER NOT NULL DEFAULT 0")
        connection.commit()
        # A tool interrupted by process exit cannot still be executing in this
        # new process. Preserve its attempt and let the normal retry policy apply.
        for row in connection.execute("SELECT run_json FROM pipeline_runs").fetchall():
            run = decode(json.loads(row["run_json"]), PipelineRun)
            states = []
            for state in run.stages:
                if state.status is StageStatus.RUNNING:
                    attempt = replace(
                        state.attempts[-1], status=StageStatus.FAILED,
                        finished_at=datetime.now(timezone.utc),
                        error_code="InterruptedError",
                        error_message="Application closed during this stage; review before retrying.",
                    )
                    state = replace(state, status=StageStatus.FAILED,
                                    attempts=(*state.attempts[:-1], attempt))
                states.append(state)
            if tuple(states) != run.stages:
                self.save(replace(run, stages=tuple(states)))

    def save(self, run):
        with self.connection:
            self.connection.execute(
                "INSERT INTO pipeline_runs (run_id, case_id, run_json, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET run_json = excluded.run_json",
                (run.id, run.case_id, json.dumps(encode(run)), run.created_at.isoformat()),
            )

    def get(self, run_id):
        row = self.connection.execute(
            "SELECT run_json FROM pipeline_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        return decode(json.loads(row["run_json"]), PipelineRun) if row else None

    def latest_for_case(self, case_id):
        row = self.connection.execute(
            "SELECT run_json FROM pipeline_runs WHERE case_id = ? AND obsolete = 0 ORDER BY rowid DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return decode(json.loads(row["run_json"]), PipelineRun) if row else None

    def active_for_case(self, case_id):
        latest = self.latest_for_case(case_id)
        return latest if latest is not None and not latest.stopped else None

    def invalidate_case(self, case_id):
        with self.connection:
            self.connection.execute("UPDATE pipeline_runs SET obsolete = 1 WHERE case_id = ?", (case_id,))
