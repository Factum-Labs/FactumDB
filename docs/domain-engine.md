# FactumDB Domain Engine

The correlation engine: the four forensic services in `backend/core/domain/`.
This is the handoff document — what the engine produces, what it refuses to
produce, and how the other layers connect to it.

Companion documents: [`correlation-rules.md`](correlation-rules.md) is the rule
catalogue every finding cites; [`canonical-model.md`](canonical-model.md) is the
input contract; [`sqlite-schema.md`](sqlite-schema.md) is the persistence side.

## What it is

Four pure services, run in pipeline order:

| Service | Answers |
|---|---|
| `TransactionGroupingService` | Which events were committed together, and what we cannot see |
| `RecordCorrelationService` | Which events and pages belong to which logical record |
| `StateReconstructionService` | What each record held, over time |
| `ReconciliationService` | Whether the log and the tablespace agree, per field and per record |

```python
grouping       = TransactionGroupingService(evidence).group(source)
correlation    = RecordCorrelationService(schemas, physical, evidence).correlate(grouping)
reconstruction = StateReconstructionService(schemas, physical, evidence).reconstruct(
                     grouping, correlation)
reconciliation = ReconciliationService(schemas, physical, evidence).reconcile(
                     reconstruction, correlation, grouping.coverage)
```

Each stage consumes only what earlier stages produced. `tests/fixtures/pipeline.py`
assembles them exactly this way.

## The five properties that constrain every design decision

1. **Deterministic.** Same evidence, byte-identical output — on any machine, in
   any process, whatever order the adapters emit rows in. Enforced by
   `test_repeatability.py`, which compares canonical JSON across repeat runs,
   reversed and shuffled inputs, and separate processes under different
   `PYTHONHASHSEED` values.
2. **Rule-based, not scored.** No fuzzy matching, no confidence numbers. Every
   classification cites a rule id from the catalogue.
3. **Never fabricate.** Ambiguity is reported as a result, never resolved by
   guessing. This is why a table with no primary key correlates nothing, why two
   live rows at one key match neither, and why a partial row image leaves columns
   unobserved rather than defaulted.
4. **Provenance on every finding** — source file, log position, transaction id,
   tool run.
5. **Pure.** No SQLite, filesystem, subprocess, `random`, `uuid`, or wall clock.
   Enforced by `test_purity.py`, which walks the AST of every domain module.

## The distinction the whole engine turns on

When a log-derived value and a tablespace value differ, that is either a
**conflict** — the evidence genuinely disagrees — or **unresolved** — a log we
were not given could contain the change that explains it.

Getting this wrong in the permissive direction means presenting an evidence gap
as tampering. It is decided in one place (`R-RECON-003` vs `R-RECON-004`), by
whether the record's coverage is complete.
`test_reconciliation_matrix.py::test_no_cell_conflicts_while_coverage_is_incomplete`
sweeps the whole classification matrix asserting nothing reaches Conflicting
under a gap.

## Output models

All frozen dataclasses. Full field lists are in the modules; this is the shape.

**`models/transactions.py`** — `TransactionGroup` (status, `incompleteness_reason`,
events, session key, `synthesised`), `UngroupedEvent`, `CoverageWindow`,
`CoverageReport`, `GroupingResult`.

**`models/correlation.py`** — `RecordCorrelation` (record, `MatchMethod`, event
refs, physical counterpart, `identity_aliases`), `CorrelationEdge`,
`EventCorrelation`, `UnsupportedTable`, `CorrelationResult`.

**`models/history.py`** — `RecordHistory` carrying three states and
`HistoryStep`s. `ReconstructionResult`.

**`models/reconciliation.py`** — `FieldReconciliation` (per column),
`RecordReconciliation` (roll-up), `ReconciliationResult`.

### Three states, deliberately not one

`RecordHistory` carries `earliest_state`, `final_log_state` and
`speculative_state`. `final_log_state` replays only committed events — it is the
engine's claim about what the database held. `speculative_state` replays
everything including rolled-back events and is **not a claim**: it exists so the
engine can notice that a tablespace value equals one a rolled-back transaction
produced, and report that coincidence (`R-RECON-030`) without concluding how it
got there. Collapsing them would let the engine assert a value that never existed.

### The value taxonomy

Five things `models/values.py` keeps apart, because collapsing any pair would
make the tool state something untrue:

| | Means | Reconciles to |
|---|---|---|
| scalar | observed value | comparable |
| `None` | real SQL NULL, observed | comparable (`NULL == NULL` is a match) |
| `UndecodableValue` | column exists, bytes unreadable | Unsupported |
| `UNOBSERVED` | no evidence mentions this column | Unresolved |
| `Presence` | record-level existence | its own row |

## Architecture decisions

**ADR-01 — three transaction statuses, not four.** `Architecture.md` §3.5 and
`README.md` say grouping yields "committed, rolled-back, incomplete, or
unresolved", but the canonical model, the SQLite `CHECK`, and the frontend
`TxStatus` all allow three. The fourth concept is carried as
`incompleteness_reason` instead. Full reasoning in
[`correlation-rules.md`](correlation-rules.md).

**ADR-02 — a record's canonical identity is its latest primary key.** The
tablespace holds the current key, so a latest-key identity makes the physical
match direct. Earlier keys become `identity_aliases`.

Both ADRs, and the note on unclaimed events (`R-GRP-005` vs `R-GRP-011`), live in
the rule catalogue.

## Frontend mapping

The frontend types in `frontend/src/data/types.ts` predate the canonical model.
They are close but not authoritative — see the audit in the implementation plan.

| Domain | Frontend | Note |
|---|---|---|
| `TransactionGroup.id`, `.status` | `Transaction.id`, `.status` | status lowercase → display case |
| `TransactionGroup.source_file` | `Transaction.binlogFile` | |
| `TransactionGroup.start_position` | `Transaction.binlogPos` | **BEGIN position, not COMMIT** |
| `CorrelationEdge` | `CorrelationEdge` | 1:1; backend adds `event_refs` |
| `FieldReconciliation.log_display` / `.phys_display` | `ReconRow.log` / `.phys` | typed values kept alongside |
| `FieldReconciliation.rule_id` | *(missing)* | needs adding for repeatability |
| `RecordReconciliation.rollup_label` | graph node subtitle | `"balance: Conflicting"` |
| `RecordRef.database` | *(missing)* | ids use short table name and can collide |

### Frontend changes needed (separate branch)

- `binlogPos` semantics → `start_position`; rolled-back and incomplete
  transactions have no COMMIT, so a commit-based sort key is undefined for
  exactly the cases that matter most.
- Replace `cmpTransaction`/`cmpKey`: order binlog files by
  `BinlogInventory.listed_files` rather than lexically, and compare key
  components numerically only for strict digit strings (`Number()` loses BIGINT
  precision, reads `"0x10"` as 16, and sorts `1|10` before `1|9`).
- Add `database` to `RecordRef` and `ruleId` to `ReconRow`.
- Fix `classify()`: `Unsupported` has severity 0, so a record whose every field is
  Unsupported currently renders as `'agreeing'` — it was never compared at all.
- Rename `R-CONFLICT-02` → `R-RECON-003` in `caseData.ts`.

`npm run check:graph` must stay green throughout.

## Persistence handoff

This answers the open TODO in [`sqlite-schema.md`](sqlite-schema.md) ("tables for
correlation results, record histories and reconciliation results are not here
yet"). Suggested tables, following the existing conventions — TEXT UUID ids,
ISO-8601 UTC, `STRICT`, `CHECK` constraints matching the enums:

`transaction_groups`, `grouped_events`, `coverage_windows`, `correlations`,
`correlation_edges`, `record_histories`, `history_steps`,
`reconciliation_fields`, `reconciliation_records`, `findings`.

Two constraints worth carrying:

```sql
-- transaction_groups: a reason exists exactly when the status is incomplete
incompleteness_reason TEXT CHECK (incompleteness_reason IN (
    'no_terminator_in_range', 'log_file_missing_in_sequence',
    'events_without_begin', 'marker_without_events')),
CHECK ((status = 'incomplete') = (incompleteness_reason IS NOT NULL))
```

**`incompleteness_reason` must not go on the existing `transactions` table.**
That table carries `tool_run_id`, which makes it adapter output — a record of
what the tool showed. The reason is a domain conclusion.

### Two canonical-model deviations

Both additive and defaulted, so existing adapter code is unaffected:

1. **`provenance` on `PhysicalRecord`, `BinlogEvent`, `TransactionMarker`.**
   Provenance-per-finding is impossible if the domain only sees
   `(source_file, log_position)`. When absent the services emit degraded
   provenance plus one `R-PROV-001` finding, so the gap is visible.
2. **`Warning` renamed `AnalysisWarning`.** `Warning` is a builtin exception and
   `warnings` a stdlib module.

## Orchestration handoff

The four signatures are the stage contracts for `RunCorrelation` and
`RunReconciliation`. Each returns a frozen result plus `findings`, so stage
failure handling never inspects domain internals. Nothing raises for evidence
problems — an unreadable value, a missing log, an ambiguous match are all
*results*, not errors.

## Verification

```bash
cd backend
pip install -e ".[dev]"
pytest -q                      # 636 tests
ruff check core tests tools
mypy                           # strict, over core/
python tools/render_rules_doc.py --check
```

**Golden snapshots.** `tests/golden/ds*.json` capture the full pipeline output
for all twelve datasets. Regenerate with `pytest --update-golden` and **read the
diff before committing** — a snapshot updated without being read launders a
regression into an approved baseline. They capture conclusions, not wording:
changing a rule's title or template produces no diff (that is guarded by the
catalogue test), while changing a classification produces a localized one —
verified by mutating Strong→Exact, which touched 50 of 950 lines in ds04 and 26
of 961 in ds08, and nothing in the other ten datasets.

### Evaluation results

Computed by `test_evaluation_metrics.py` from `Expected` blocks written by hand
from the evidence, independently of the implementation:

| Metric | Result |
|---|---|
| Transaction boundary accuracy | 16/16 = 1.000 |
| Record correlation accuracy | 15/15 = 1.000 |
| Reconciliation accuracy | 20/20 = 1.000 |
| False positives | 0 |
| False negatives | 0 |

Print the table with
`pytest tests/domain/test_evaluation_metrics.py::test_evaluation_table -s`.

A false positive here means the engine called something a conflict when the
evidence could not support it — the failure mode that would discredit a report.

### The twelve datasets

| id | Scenario |
|---|---|
| ds01 | Single-row insert, update, delete |
| ds02 | Multi-table committed transaction, all agreeing |
| ds03 | Rolled-back value present in the tablespace |
| ds04 | Transaction left open where the log ends |
| ds05 | Two concurrent sessions interleaved |
| ds06 | Composite primary key |
| ds07 | Primary key changed by an update |
| ds08 | Values differ across a missing binary log |
| ds09 | Undecodable value and unvalidated column type |
| ds10 | Damaged InnoDB pages |
| ds11 | Table with no primary key |
| ds12 | Partial row image |

They map onto the week 7 evaluation list in the work distribution plan.

## Scope

**In:** deterministic rule-based correlation over the canonical model, for
MySQL 8.4.x, InnoDB, file-per-table, row-based logging, tables with explicit
primary keys (single and composite), and a validated subset of data types.

**Out, deliberately:** confidence scoring (deferred in the work plan), fuzzy
matching, recovering values the evidence does not contain, and any conclusion
about who made a change or why.

**Not yet built:** SQLite persistence of these results, the adapters that feed
them, and the Tauri wiring. The engine is pure and tested against in-memory
fixtures; those layers are separate branches.
