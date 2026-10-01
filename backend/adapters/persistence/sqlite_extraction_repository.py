"""SQLite implementation of the application's ExtractionRepository.

The extraction use cases save through one port with a method per stage, while
persistence has a repository per table. This class sits between the two: each
save_* method passes its data on to the right repositories. It does for
storage what adapters/tools/extraction.py does for the tools.

Two things the port does not provide are handled here.

Which tool run produced the data. Every table holding extracted data needs a
tool_run_id, but the port's methods only take the case and evidence ids.
Until the port carries the run id, each save looks up the most recent
successful run of the matching tool for that evidence file, and refuses to
save if there is none. Extracted data with no run behind it would make the
provenance claim false, so refusing is the better failure.

That lookup has one known limit. With deleted-row recovery on, ibd2sql runs
twice on the same file, and both sets of rows are attributed to the later
run. Passing the run id through the port would remove the guess.

Saving a decoded binlog as one unit. Its events, markers and warnings are
saved inside one transaction(), so either the whole decode is stored or none
of it is. A half-saved decode - events with no transactions - would look
complete and be wrong.
"""

from typing import Sequence

from adapters.persistence._transactions import transaction
from adapters.persistence.sqlite_binlog_event_repository import SqliteBinlogEventRepository
from adapters.persistence.sqlite_integrity_repository import SqliteIntegrityRepository
from adapters.persistence.sqlite_physical_record_repository import (
    SqlitePhysicalRecordRepository,
)
from adapters.persistence.sqlite_schema_repository import SqliteSchemaRepository
from adapters.persistence.sqlite_transaction_repository import SqliteTransactionRepository
from adapters.persistence.sqlite_warning_repository import SqliteWarningRepository
from core.application.errors import PrerequisiteError
from core.application.models import DecodedBinlog, NormalizedEvidence
from core.domain.models.canonical import IntegrityResult, PhysicalRecord, Schema


class SqliteExtractionRepository:
    """Stores each extraction stage's output in the case database."""

    def __init__(self, connection):
        self._connection = connection
        self._integrity = SqliteIntegrityRepository(connection)
        self._schemas = SqliteSchemaRepository(connection)
        self._records = SqlitePhysicalRecordRepository(connection)
        self._events = SqliteBinlogEventRepository(connection)
        self._transactions = SqliteTransactionRepository(connection)
        self._warnings = SqliteWarningRepository(connection)

    def save_integrity(self, case_id: str, evidence_id: str,
                       result: IntegrityResult) -> None:
        run_id = self._tool_run_for(case_id, evidence_id, "innochecksum")
        self._integrity.save(result, evidence_id, run_id)

    def save_schemas(self, case_id: str, evidence_id: str,
                     schemas: Sequence[Schema]) -> None:
        run_id = self._tool_run_for(case_id, evidence_id, "ibd2sdi")
        with transaction(self._connection):
            for schema in schemas:
                self._schemas.save(schema, evidence_id, run_id)

    def save_physical_records(self, case_id: str, evidence_id: str,
                              records: Sequence[PhysicalRecord]) -> None:
        """An empty list still needs a run.

        "No rows found" is only a finding if the tool is known to have run.
        """
        run_id = self._tool_run_for(case_id, evidence_id, "ibd2sql")
        self._records.save_many(records, evidence_id, run_id)

    def save_decoded_binlog(self, case_id: str, evidence_id: str,
                            decoded: DecodedBinlog) -> None:
        """Events, then markers, then warnings, all in one transaction.

        Events go first because the markers link to them. Warnings are saved
        even when there are no events - a decode that skipped everything is
        exactly when the warnings matter most.
        """
        run_id = self._tool_run_for(case_id, evidence_id, "mysqlbinlog")
        with transaction(self._connection):
            self._events.save_many(decoded.events, evidence_id, run_id)
            self._transactions.save_many(decoded.markers, evidence_id, run_id)
            self._warnings.save_many(decoded.warnings, case_id, evidence_id, run_id)

    def save_normalized(self, case_id: str, normalized: NormalizedEvidence) -> None:
        """Not implemented yet, on purpose.

        The extraction stages already store canonical schemas, rows, events
        and markers, and there is no normaliser yet to say what normalisation
        changes about them. Storing the same data a second time could leave
        two copies that disagree, and silently doing nothing would lose
        anything a normaliser did change. Until that is agreed, this fails
        loudly.
        """
        raise NotImplementedError(
            "normalised evidence has no storage yet: the extraction stages "
            "already store the canonical data, and what normalisation adds "
            "has not been agreed"
        )

    def _tool_run_for(self, case_id: str, evidence_id: str, tool_name: str) -> str:
        """The latest successful run of this tool on this file, in this case.

        Scoping by case as well as evidence means evidence from another case
        can never borrow a run from this one.
        """
        row = self._connection.execute(
            """
            SELECT tool_run_id FROM tool_runs
            WHERE case_id = ? AND evidence_id = ? AND tool_name = ?
              AND status = 'succeeded'
            ORDER BY finished_at DESC, rowid DESC
            LIMIT 1
            """,
            (case_id, evidence_id, tool_name),
        ).fetchone()
        if row is None:
            raise PrerequisiteError(
                f"no successful {tool_name} run is recorded for evidence "
                f"{evidence_id} in case {case_id}, so its output cannot be "
                f"saved with provenance"
            )
        return row["tool_run_id"]
