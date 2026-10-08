"""Application-facing facade over the existing SQLite extraction stores."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from adapters.persistence._in_case import in_case
from core.application.models import DecodedBinlog, NormalizedEvidence
from core.application.errors import ConflictError, NotFoundError, PrerequisiteError


class SqliteExtractionRepository:
    def __init__(self, connection, *, integrity, schemas, physical, events,
                 transactions, warnings, scopes, normalizations, inventory) -> None:
        self._connection = connection
        self._integrity = integrity
        self._schemas = schemas
        self._physical = physical
        self._events = events
        self._transactions = transactions
        self._warnings = warnings
        self._scopes = scopes
        self._normalizations = normalizations
        self._inventory = inventory

    def save_integrity(self, case_id, evidence_id, tool_run_id, result) -> None:
        with self._atomic():
            # innochecksum exits 1 when it finds a damaged page, so the run
            # that finds damage is recorded as failed - and on a damaged file
            # the -S run fails too. Accepting only successful runs would make
            # damage, the most important result this stage has, unsaveable.
            # The adapter refuses runs that failed for any other reason.
            self._validate_provenance(
                case_id, evidence_id, tool_run_id, "innochecksum", allow_failed=True
            )
            self._integrity.save(result, evidence_id, tool_run_id)

    def save_schemas(self, case_id, evidence_id, tool_run_id, schemas) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id, "ibd2sdi")
            for schema in schemas:
                self._schemas.save(schema, evidence_id, tool_run_id)

    def save_physical_records(self, case_id, evidence_id, tool_run_id, records) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id, "ibd2sql")
            self._physical.save_many(records, evidence_id, tool_run_id)

    def save_decoded_binlog(
        self, case_id: str, evidence_id: str, tool_run_id: str, decoded: DecodedBinlog,
    ) -> None:
        with self._atomic():
            self._validate_provenance(case_id, evidence_id, tool_run_id, "mysqlbinlog")
            decoded = self._under_registered_name(evidence_id, decoded)
            self._events.save_many(decoded.events, evidence_id, tool_run_id)
            self._transactions.save_many(decoded.markers, evidence_id, tool_run_id)
            self._warnings.save_many(decoded.warnings, case_id, evidence_id, tool_run_id)

    def _under_registered_name(self, evidence_id: str, decoded: DecodedBinlog) -> DecodedBinlog:
        """The decode, with its events and markers under the binlog's own name.

        The adapter names events after the file it read, and that file is the
        working copy, e.g. "<evidence id>-mysql-bin.000006". The server's
        index - and anyone reading the report - knows the log as
        "mysql-bin.000006", the name it was registered under. Ordering the
        logs and spotting missing ones both match on that name, so it is the
        one stored.

        One evidence file is one binlog. A decode claiming events from more
        than one file was put together wrongly, and renaming them all would
        hide that, so it is refused.
        """
        name = self._connection.execute(
            "SELECT filename FROM evidence_files WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()["filename"]
        files = {e.source_file for e in decoded.events} | {m.source_file for m in decoded.markers}
        if len(files) > 1:
            raise ConflictError(
                f"one decoded binlog holds events from {len(files)} files: {sorted(files)}"
            )
        if not files or files == {name}:
            return decoded
        (read_as,) = files
        return DecodedBinlog(
            tuple(replace(e, source_file=name) for e in decoded.events),
            tuple(replace(m, source_file=name) for m in decoded.markers),
            tuple(
                replace(w, context={**w.context, "source_file": name})
                if w.context.get("source_file") == read_as else w
                for w in decoded.warnings
            ),
        )

    def save_normalized(self, case_id: str, normalized: NormalizedEvidence) -> None:
        """Record which part of the stored evidence the analysis covers.

        The extraction stages already stored the canonical data, so it is not
        copied a second time - two copies could drift apart. What is saved is
        the scope that was used and, for each kind of evidence, how much was
        in scope out of how much is stored.
        """
        with self._atomic():
            if self._connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone() is None:
                raise NotFoundError(f"case not found: {case_id}")
            stored = self._stored_counts(case_id)
            counts = {
                "schemas": (len(normalized.schemas), stored["schemas"]),
                "physical_records": (len(normalized.physical_records), stored["physical_records"]),
                "events": (len(normalized.events), stored["events"]),
                "markers": (len(normalized.markers), stored["markers"]),
            }
            for kind, (in_scope, total) in counts.items():
                if in_scope > total:
                    # More than the database holds cannot have come from it,
                    # and the analysis reads from the database.
                    raise ConflictError(
                        f"normalized evidence has {in_scope} {kind} but the case "
                        f"database stores only {total}"
                    )
            self._normalizations.save(case_id, self._scopes.scope_for(case_id), counts)
            # Every analysis result was built on the previous normalization,
            # so none of them describes the evidence any more.
            self._connection.execute(
                "DELETE FROM analysis_results WHERE case_id = ?", (case_id,)
            )

    def save_inventory(self, case_id: str, evidence_id: str, inventory) -> None:
        """Store what a binlog index listed against what was seized.

        There is no tool run behind an inventory - the index is read as a
        plain file - so the evidence is checked instead: it has to be this
        case's binlog index, whose registered hash is what ties the
        inventory to the file it came from.
        """
        with self._atomic():
            evidence = self._connection.execute(
                "SELECT case_id, kind FROM evidence_files WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            if evidence is None:
                raise NotFoundError(f"evidence not found: {evidence_id}")
            if evidence["case_id"] != case_id:
                raise ConflictError("evidence does not belong to the supplied case")
            if evidence["kind"] != "binlog_index":
                raise ConflictError(
                    f"an inventory can only come from a binlog index, not {evidence['kind']}"
                )
            self._inventory.save(inventory, evidence_id)

    def _stored_counts(self, case_id: str) -> dict[str, int]:
        """How much of each kind of evidence this case has stored."""
        condition, args = in_case(case_id)

        def count(sql: str) -> int:
            return self._connection.execute(sql, args).fetchone()[0]

        return {
            # One schema per table, however many files it was extracted from.
            "schemas": count(
                "SELECT COUNT(*) FROM (SELECT DISTINCT database_name, table_name "
                f"FROM schemas WHERE {condition})"
            ),
            "physical_records": count(f"SELECT COUNT(*) FROM physical_records WHERE {condition}"),
            "events": count(f"SELECT COUNT(*) FROM binlog_events WHERE {condition}"),
            "markers": count(f"SELECT COUNT(*) FROM transactions WHERE {condition}"),
        }

    def _validate_provenance(self, case_id: str, evidence_id: str, tool_run_id: str,
                             tool_name: str, *, allow_failed: bool = False) -> None:
        evidence = self._connection.execute(
            "SELECT case_id FROM evidence_files WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if evidence is None:
            raise NotFoundError(f"evidence not found: {evidence_id}")
        if evidence["case_id"] != case_id:
            raise ConflictError("evidence does not belong to the supplied case")
        run = self._connection.execute(
            "SELECT case_id, evidence_id, tool_name, status, exit_code FROM tool_runs "
            "WHERE tool_run_id = ?",
            (tool_run_id,),
        ).fetchone()
        if run is None:
            raise NotFoundError(f"tool run not found: {tool_run_id}")
        if run["case_id"] != case_id or run["evidence_id"] != evidence_id:
            raise ConflictError("tool run does not belong to the supplied case and evidence")
        if run["tool_name"] != tool_name:
            # Schemas pointing at an innochecksum run would be provenance
            # that is present but false.
            raise ConflictError(
                f"{tool_name} output cannot point at a {run['tool_name']} run"
            )
        if allow_failed and run["status"] == "failed":
            return
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
