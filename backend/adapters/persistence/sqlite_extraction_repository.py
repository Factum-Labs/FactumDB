"""Application-facing facade over the existing SQLite extraction stores."""

from __future__ import annotations

from contextlib import contextmanager

from core.application.models import DecodedBinlog, NormalizedEvidence
from core.application.errors import ConflictError, NotFoundError, PrerequisiteError


class SqliteExtractionRepository:
    def __init__(self, connection, *, integrity, schemas, physical, events,
                 transactions, warnings) -> None:
        self._connection = connection
        self._integrity = integrity
        self._schemas = schemas
        self._physical = physical
        self._events = events
        self._transactions = transactions
        self._warnings = warnings

    def save_integrity(self, case_id, evidence_id, tool_run_id, result) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id)
            self._integrity.save(result, evidence_id, tool_run_id)

    def save_schemas(self, case_id, evidence_id, tool_run_id, schemas) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id)
            for schema in schemas:
                self._schemas.save(schema, evidence_id, tool_run_id)

    def save_physical_records(self, case_id, evidence_id, tool_run_id, records) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id)
            self._physical.save_many(records, evidence_id, tool_run_id)

    def save_decoded_binlog(
        self, case_id: str, evidence_id: str, tool_run_id: str, decoded: DecodedBinlog,
    ) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id)
            self._events.save_many(decoded.events, evidence_id, tool_run_id)
            self._transactions.save_many(decoded.markers, evidence_id, tool_run_id)
            self._warnings.save_many(decoded.warnings, case_id, evidence_id, tool_run_id)

    def save_normalized(self, case_id: str, normalized: NormalizedEvidence) -> None:
        raise NotImplementedError(
            "normalized evidence persistence is not available in the current SQLite schema"
        )

    def _validate_provenance(self, case_id: str, evidence_id: str, tool_run_id: str) -> None:
        evidence = self._connection.execute(
            "SELECT case_id FROM evidence_files WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if evidence is None:
            raise NotFoundError(f"evidence not found: {evidence_id}")
        if evidence["case_id"] != case_id:
            raise ConflictError("evidence does not belong to the supplied case")
        run = self._connection.execute(
            "SELECT case_id, evidence_id, status, exit_code FROM tool_runs WHERE tool_run_id = ?",
            (tool_run_id,),
        ).fetchone()
        if run is None:
            raise NotFoundError(f"tool run not found: {tool_run_id}")
        if run["case_id"] != case_id or run["evidence_id"] != evidence_id:
            raise ConflictError("tool run does not belong to the supplied case and evidence")
        if run["status"] != "succeeded" or run["exit_code"] != 0:
            raise PrerequisiteError("extraction results require a successful tool run")

    @contextmanager
    def _atomic(self):
        atomic = getattr(self._connection, "atomic", None)
        if atomic is not None:
            with atomic():
                yield
        else:
            with self._connection:
                yield


class TransactionalConnection:
    """Suppress nested repository commits while a facade operation is active."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self._atomic_depth = 0

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        if self._atomic_depth == 0:
            self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._atomic_depth == 0:
            return self._connection.__exit__(exc_type, exc, traceback)
        return False

    @contextmanager
    def atomic(self):
        outermost = self._atomic_depth == 0
        if outermost:
            self._connection.execute("BEGIN")
        self._atomic_depth += 1
        try:
            yield
        except Exception:
            self._atomic_depth -= 1
            if outermost:
                self._connection.rollback()
            raise
        else:
            self._atomic_depth -= 1
            if outermost:
                self._connection.commit()
