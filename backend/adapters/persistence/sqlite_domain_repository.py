"""SQLite implementation of the application's DomainRepository.

It has two jobs.

inputs_for() gives the domain services the case's evidence through the domain
ports: schema catalog, event source, physical records and evidence context. It
reads the evidence the way the case was last normalized - the same scope,
applied by the same function. If the evidence changed after that
normalization, for example a binlog decoded again, the in-scope counts no
longer match and the analysis is refused until the case is normalized again.
Running on evidence the normalization never saw would make its counts, and
the report built on them, untrue. Matching counts are a cheap check rather
than a proof, but they catch the ordinary way this goes wrong.

The save and load methods keep the services' four results, one JSON document
per case and stage (see _results.py). The results build on each other -
correlation uses the grouping, reconstruction uses both - so saving one
removes every result after it. A later stage can then never load a result
that was made from an older version of an earlier one: it finds nothing, and
the use case says which stage has to run first.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone

from adapters.persistence._results import decode, encode
from adapters.persistence._timestamps import to_text
from adapters.persistence.sqlite_evidence_normalizer import scoped_evidence
from core.application.errors import NotFoundError, PrerequisiteError
from core.application.ports import DomainInputs
from core.domain.models.correlation import CorrelationResult
from core.domain.models.history import ReconstructionResult
from core.domain.models.reconciliation import ReconciliationResult
from core.domain.models.transactions import GroupingResult
from core.domain.ports import DEFAULT_SUPPORTED_TYPES

# In the order the pipeline runs them, which is also the order they build on.
STAGES = ("grouping", "correlation", "reconstruction", "reconciliation")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteDomainRepository:
    """The domain services' view of a case database, and their results."""

    def __init__(self, connection, *, cases, normalizations, schemas, physical,
                 events, transactions, integrity, inventory, tool_runs, now=_utc_now):
        self._connection = connection
        self._cases = cases
        self._normalizations = normalizations
        self._schemas = schemas
        self._physical = physical
        self._events = events
        self._transactions = transactions
        self._integrity = integrity
        self._inventory = inventory
        self._tool_runs = tool_runs
        self._now = now

    # ── Inputs ───────────────────────────────────────────────────────────────

    def inputs_for(self, case_id: str) -> DomainInputs:
        if self._cases.get(case_id) is None:
            raise NotFoundError(f"case not found: {case_id}")
        normalization = self._normalizations.find(case_id)
        if normalization is None:
            raise PrerequisiteError("the case's evidence must be normalized before analysis")

        evidence = scoped_evidence(
            normalization.scope,
            case_id=case_id,
            schemas=self._schemas,
            physical=self._physical,
            events=self._events,
            transactions=self._transactions,
        )
        now = {
            "schemas": len(evidence.schemas),
            "physical_records": len(evidence.physical_records),
            "events": len(evidence.events),
            "markers": len(evidence.markers),
        }
        then = {kind: in_scope for kind, (in_scope, _) in normalization.counts.items()}
        if now != then:
            raise PrerequisiteError(
                "the evidence changed after the case was normalized; normalize it again"
            )

        return DomainInputs(
            schemas=_SchemaCatalog(evidence.schemas),
            events=_EventSource(evidence.events, evidence.markers),
            physical=_PhysicalRecords(evidence.physical_records),
            evidence=_EvidenceContext(
                normalization.scope,
                case_id=case_id,
                integrity=self._integrity,
                inventory=self._inventory,
                tool_runs=self._tool_runs,
                physical=self._physical,
            ),
        )

    # ── Results ──────────────────────────────────────────────────────────────

    def save_grouping(self, case_id: str, result: GroupingResult) -> None:
        self._save(case_id, "grouping", result)

    def load_grouping(self, case_id: str) -> GroupingResult | None:
        return self._load(case_id, "grouping", GroupingResult)

    def save_correlation(self, case_id: str, result: CorrelationResult) -> None:
        self._save(case_id, "correlation", result)

    def load_correlation(self, case_id: str) -> CorrelationResult | None:
        return self._load(case_id, "correlation", CorrelationResult)

    def save_reconstruction(self, case_id: str, result: ReconstructionResult) -> None:
        self._save(case_id, "reconstruction", result)

    def load_reconstruction(self, case_id: str) -> ReconstructionResult | None:
        return self._load(case_id, "reconstruction", ReconstructionResult)

    def save_reconciliation(self, case_id: str, result: ReconciliationResult) -> None:
        self._save(case_id, "reconciliation", result)

    def load_reconciliation(self, case_id: str) -> ReconciliationResult | None:
        """Not part of the port yet; the report will need it."""
        return self._load(case_id, "reconciliation", ReconciliationResult)

    def _save(self, case_id: str, stage: str, result) -> None:
        later = STAGES[STAGES.index(stage) + 1:]
        with self._connection:
            if later:
                self._connection.execute(
                    "DELETE FROM analysis_results WHERE case_id = ? AND stage IN "
                    f"({', '.join('?' * len(later))})",
                    (case_id, *later),
                )
            self._connection.execute(
                "INSERT OR REPLACE INTO analysis_results "
                "(case_id, stage, result_json, saved_at) VALUES (?, ?, ?, ?)",
                (case_id, stage, json.dumps(encode(result)), to_text(self._now())),
            )

    def _load(self, case_id: str, stage: str, result_type):
        row = self._connection.execute(
            "SELECT result_json FROM analysis_results WHERE case_id = ? AND stage = ?",
            (case_id, stage),
        ).fetchone()
        return decode(json.loads(row["result_json"]), result_type) if row else None


# ── The domain ports, over one case's normalized evidence ───────────────────


class _SchemaCatalog:
    def __init__(self, schemas):
        self._by_table = {(s.database, s.table): s for s in schemas}

    def schema_for(self, database, table):
        return self._by_table.get((database, table))

    def tables(self):
        return sorted(self._by_table)


class _EventSource:
    def __init__(self, events, markers):
        self._events = tuple(events)
        self._markers = tuple(markers)

    def events(self):
        return self._events

    def markers(self):
        return self._markers


class _PhysicalRecords:
    def __init__(self, records):
        self._by_table = defaultdict(list)
        for record in records:
            self._by_table[(record.database, record.table)].append(record)

    def records_for(self, database, table):
        return tuple(self._by_table.get((database, table), ()))


class _EvidenceContext:
    """What one case's evidence as a whole can and cannot tell, within the scope."""

    def __init__(self, scope, *, case_id, integrity, inventory, tool_runs, physical):
        self._scope = scope
        self._case_id = case_id
        self._integrity = integrity
        self._inventory = inventory
        self._tool_runs = tool_runs
        self._physical = physical

    def inventory(self):
        return self._inventory.inventory(case_id=self._case_id)

    def integrity_for(self, database, table):
        if not self._scope.includes(database, table):
            return None
        return self._integrity.integrity_for(database, table, case_id=self._case_id)

    def provenance_for(self, ref):
        return self._tool_runs.provenance_for(ref, case_id=self._case_id)

    def supported_data_types(self):
        return DEFAULT_SUPPORTED_TYPES

    def tables_with_physical_evidence(self):
        return frozenset(
            pair for pair in self._physical.tables_with_physical_evidence(case_id=self._case_id)
            if self._scope.includes(*pair)
        )
