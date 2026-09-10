# Correlation Engine Output Schema

## What this is

These are the tables for what my four domain services produce: `RecordCorrelationService`, `TransactionGroupingService`, `StateReconstructionService`, and `ReconciliationService`. The models are in `backend/core/domain/models/{correlation,transactions,history,reconciliation}.py`.

This is meant to sit alongside `docs/sqlite-schema.md` - Chethana's schema for what the adapters extract - and follows its conventions exactly: `STRICT` on every table, UUID `TEXT` primary keys, snake_case names, `_json` columns with `CHECK (json_valid(...))`, and real link tables (not JSON) wherever a list references rows that already have a table, following her `transaction_events` precedent.

Two things are new here, because these tables hold *derived* data rather than *extracted* data:

- There is no `tool_run_id` on these tables. A `RecordCorrelation` was not produced by running an external tool against a file - it was produced by my own domain service reasoning over rows that are already in this database, so the correct provenance is "traceable to the log/physical rows it cites," which the link tables below give for free. What I do carry, once, is `case_id`, since a full correlation/reconstruction/reconciliation pass is scoped to one case's whole evidence set rather than to one evidence file.
- Every list-of-scalars field is JSON, same as Chethana's rule. Every list field that names *other rows this schema already has a table for* is a link table, same reasoning as her `transaction_events` - I extend that rule rather than replace it.

Written against SQLite 3.46.1, same as `docs/sqlite-schema.md`. `PRAGMA foreign_keys = ON;` and `PRAGMA journal_mode = WAL;` still have to be set on every connection - see that doc for why.

---

## 1. records

```sql
CREATE TABLE records (
    record_id   TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    database    TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    key_json    TEXT NOT NULL CHECK (json_valid(key_json)),
    key         TEXT NOT NULL,
    pk          TEXT NOT NULL,
    label       TEXT NOT NULL
) STRICT;

CREATE INDEX idx_records_table ON records(database, table_name);
```

One row per `RecordRef`. `record_id` is `RecordRef.id` verbatim (e.g. `accounts:101`) so every other table below can use it as a foreign key without re-deriving it. `key_json` is `key_columns`/`key_values` zipped into an ordered array of `{"column": ..., "value": ...}` objects - I keep both the machine form and the rendered `key` string because the rendered form is a display convenience and the JSON form is what a composite-key lookup actually needs.

---

## 2. findings

```sql
CREATE TABLE findings (
    finding_id   TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES cases(case_id),
    rule_id      TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('info', 'notice', 'warning')),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN
                    ('case', 'evidence', 'table', 'transaction', 'record', 'field', 'event')),
    subject_id   TEXT NOT NULL,
    context_json TEXT NOT NULL CHECK (json_valid(context_json)),
    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json))
) STRICT;

CREATE INDEX idx_findings_subject ON findings(subject_kind, subject_id);
CREATE INDEX idx_findings_rule    ON findings(rule_id);
```

`Finding` fires against seven different kinds of subject, so `subject_id` cannot be a single `REFERENCES` - a case id, a record id and an `(source_file, log_position)` pair are not the same key space. `subject_kind` plus `subject_id` is what every other domain model already does with `SubjectRef`, so I kept it as a pair here too rather than inventing a table-per-kind scheme.

`provenance_json` is a JSON array of `{"evidence_id", "tool_name", "tool_run_id", "source_file", "log_position"}` objects, not a link table, even though it references rows that exist elsewhere (`tool_runs`, `binlog_events`). Findings are read-heavy and write-once - nothing ever looks up "every finding citing this tool run" the way `schema_columns` gets looked up on every row event - so the FK enforcement a link table buys is not worth a join on the hot path (rendering the report).

The index on `(subject_kind, subject_id)` is there because "show every finding about this record" is exactly what a record's detail view asks for.

---

## Correlation results (`RecordCorrelationService`)

### 3. record_correlations

```sql
CREATE TABLE record_correlations (
    record_id TEXT PRIMARY KEY REFERENCES records(record_id),
    case_id   TEXT NOT NULL REFERENCES cases(case_id),
    method    TEXT NOT NULL CHECK (method IN (
                  'primary_key_exact', 'composite_primary_key_exact',
                  'primary_key_update_continuity', 'log_only_no_physical_counterpart',
                  'physical_only_no_log_events', 'ambiguous',
                  'table_has_no_primary_key', 'schema_not_available',
                  'key_columns_not_in_row_image'))
) STRICT;
```

One row per `RecordCorrelation`; `record_id` doubles as the PK since a record has exactly one correlation outcome per case. Everything else the model carries - `log_event_refs`, `transaction_ids`, `physical`/`physical_candidates`, `identity_aliases`, `findings`, `provenance` - is a list referencing rows this schema already has tables for, so each gets its own link table below rather than a JSON column, following Chethana's `transaction_events` precedent.

### 4. record_correlation_events

```sql
CREATE TABLE record_correlation_events (
    record_id    TEXT NOT NULL REFERENCES record_correlations(record_id),
    evidence_id  TEXT NOT NULL,
    source_file  TEXT NOT NULL,
    log_position INTEGER NOT NULL,
    PRIMARY KEY (record_id, evidence_id, source_file, log_position),
    FOREIGN KEY (evidence_id, source_file, log_position)
        REFERENCES binlog_events(evidence_id, source_file, log_position)
) STRICT;
```

Backs `RecordCorrelation.log_event_refs`. `EventRef` is `(source_file, log_position)`, which is not globally unique on its own - Chethana's `binlog_events` unique key needs `evidence_id` too - so this link table carries the same triple she uses, and the `FOREIGN KEY` clause is on that composite unique key rather than `binlog_events.event_id`, since `EventRef` never carries the surrogate id.

### 5. record_correlation_transactions

```sql
CREATE TABLE record_correlation_transactions (
    record_id      TEXT NOT NULL REFERENCES record_correlations(record_id),
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
    PRIMARY KEY (record_id, transaction_id)
) STRICT;
```

Backs `RecordCorrelation.transaction_ids` - which transactions touched this record.

### 6. record_identity_aliases

```sql
CREATE TABLE record_identity_aliases (
    record_id TEXT NOT NULL REFERENCES record_correlations(record_id),
    alias_id  TEXT NOT NULL REFERENCES records(record_id),
    PRIMARY KEY (record_id, alias_id)
) STRICT;
```

Backs `RecordCorrelation.identity_aliases`. Kept separate from `record_correlation_transactions` even though both are `(record_id, other_id)` pairs, because an alias points at another `records` row and a transaction link points at a `transactions` row - merging them into one polymorphic table would trade a real foreign key for a string tag, which is the exact tradeoff the `findings` table already rejected.

### 7. record_physical_matches

```sql
CREATE TABLE record_physical_matches (
    record_id           TEXT NOT NULL REFERENCES record_correlations(record_id),
    physical_record_id  TEXT NOT NULL REFERENCES physical_records(record_id),
    is_primary          INTEGER NOT NULL CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (record_id, physical_record_id)
) STRICT;

CREATE INDEX idx_record_physical_primary ON record_physical_matches(record_id, is_primary);

CREATE UNIQUE INDEX idx_physical_match_primary_owner
    ON record_physical_matches(physical_record_id)
    WHERE is_primary = 1;
```

Backs `RecordCorrelation.physical` and `.physical_candidates` together - `physical` is just whichever candidate has `is_primary = 1`, so there is no reason to store it twice. This is also why `PhysicalRecordRef` gets no table of its own: every field it carries (`database`, `table`, `is_deleted`, `page_no`, `page_offset`, `provenance`) already exists on `physical_records`, so a `PhysicalRecordRef` is nothing but a pointer to a `physical_records` row plus the fact that the correlator considered it a candidate. Turning it into its own table would mean keeping two copies of the same page location in sync.

The partial unique index is what enforces "a physical row can only ever belong to one record's key" - at most one `is_primary = 1` row per `physical_record_id` across the whole table, checked by SQLite itself rather than by convention. I originally carried this as a plain column on `physical_records`, but that meant the same fact lived in two places with nothing keeping them in sync, and it collided with `physical_records.record_id` (`docs/sqlite-schema.md` §6), which is the physical row's own primary key, not a pointer to anything in this schema. This table is the single source of truth for the relationship instead - `physical_records` gets no amendment at all.

`MatchMethod.PHYSICAL_ONLY` (a physical row with no log-derived identity) is simply a `physical_records` row with no matching entry here, so the "unmatched" case needs no null to represent it. The reverse lookup - "which record does this physical row belong to" - is a join instead of a column read:

```sql
SELECT record_id FROM record_physical_matches
WHERE physical_record_id = ? AND is_primary = 1;
```

### 8. event_correlations

```sql
CREATE TABLE event_correlations (
    event_correlation_id TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    evidence_id     TEXT NOT NULL,
    source_file     TEXT NOT NULL,
    log_position    INTEGER NOT NULL,
    event_type      TEXT NOT NULL CHECK (event_type IN ('INSERT', 'UPDATE', 'DELETE')),
    method          TEXT NOT NULL CHECK (method IN (
                        'primary_key_exact', 'composite_primary_key_exact',
                        'primary_key_update_continuity', 'log_only_no_physical_counterpart',
                        'physical_only_no_log_events', 'ambiguous',
                        'table_has_no_primary_key', 'schema_not_available',
                        'key_columns_not_in_row_image')),
    rule_id         TEXT NOT NULL,
    transaction_id  TEXT REFERENCES transactions(transaction_id),
    record_id       TEXT REFERENCES records(record_id),
    FOREIGN KEY (evidence_id, source_file, log_position)
        REFERENCES binlog_events(evidence_id, source_file, log_position),
    UNIQUE (evidence_id, source_file, log_position)
) STRICT;

CREATE INDEX idx_event_correlations_record ON event_correlations(record_id);
```

This is the per-event mirror of `record_correlations` - one row for *every* binlog event, including the ones that could not be linked to a record at all (`record_id` is null exactly when `EventCorrelation.record_id` is `None`). I keep this as its own table rather than folding it into `binlog_events` because it belongs to a different pipeline stage: `binlog_events` is what the adapter extracted, `event_correlations` is what my service concluded about it, and conflating the two would mean an extraction table's schema has to change every time I add a new correlation rule.

`findings` for both this table and `record_correlations` live in the shared `findings` table (§2) keyed by `subject_kind = 'event'` / `'record'` and the matching `subject_id` - I did not give either table its own `findings_json` column, to avoid the same finding data existing in two places with two different serialisations.

### 9. unsupported_tables

```sql
CREATE TABLE unsupported_tables (
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    database    TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    PRIMARY KEY (case_id, database, table_name)
) STRICT;
```

Backs `CorrelationResult.unsupported_tables` directly - small enough, and looked up rarely enough (once, when building the "tables we could not analyse" section of the report), that it does not need a surrogate id.

`CorrelationEdge` gets no table of its own: `tx_id`/`record_id`/`event_type` is exactly `record_correlation_transactions` joined against `event_correlations` grouped by `event_type`, and `event_refs` is `record_correlation_events` filtered to that transaction. Materialising it separately would mean keeping a derived view in sync by hand.

---

## Transaction grouping (`TransactionGroupingService`)

### 10. Amendment to `transactions` (docs/sqlite-schema.md §8)

`TransactionGroup` is what `TransactionMarker` becomes after grouping, and it carries five fields the existing `transactions` table does not: `session_key`, `synthesised`, `commit_position`, `commit_timestamp`, `incompleteness_reason`. Rather than add a second table for the same entity, I extend the one Chethana already has:

```sql
ALTER TABLE transactions ADD COLUMN case_id TEXT REFERENCES cases(case_id);
ALTER TABLE transactions ADD COLUMN session_key TEXT NOT NULL DEFAULT '';
ALTER TABLE transactions ADD COLUMN synthesised INTEGER NOT NULL DEFAULT 0 CHECK (synthesised IN (0, 1));
ALTER TABLE transactions ADD COLUMN commit_position INTEGER;
ALTER TABLE transactions ADD COLUMN commit_timestamp TEXT;
ALTER TABLE transactions ADD COLUMN incompleteness_reason TEXT CHECK (incompleteness_reason IS NULL OR incompleteness_reason IN (
    'no_terminator_in_range', 'log_file_missing_in_sequence',
    'events_without_begin', 'marker_without_events'));

CREATE INDEX idx_transactions_case ON transactions(case_id);
```

(SQLite's `ALTER TABLE ADD COLUMN` cannot add a `NOT NULL` column without a default on a table that may already hold rows, which is why `session_key`/`synthesised` get defaults even though the dataclass fields are not optional going forward.)

`incompleteness_reason` is only ever non-null when `status = 'incomplete'`, but I left that as a comment rather than a `CHECK` tying the two columns together - SQLite `CHECK` constraints can reference other columns in the same row, so it is possible, but the enum list is long enough that the combined expression stops being readable, and `IncompletenessReason`'s own docstring already states the invariant and is asserted by `tests/domain/test_rules_catalogue.py`.

`transaction_events.event_order` (`docs/sqlite-schema.md` §9) already is `GroupedEvent.order`, so no change is needed there - grouping's event list slots directly into the table built for the marker's event list.

### 11. ungrouped_events

```sql
CREATE TABLE ungrouped_events (
    case_id      TEXT NOT NULL REFERENCES cases(case_id),
    evidence_id  TEXT NOT NULL,
    source_file  TEXT NOT NULL,
    log_position INTEGER NOT NULL,
    rule_id      TEXT NOT NULL,
    PRIMARY KEY (evidence_id, source_file, log_position),
    FOREIGN KEY (evidence_id, source_file, log_position)
        REFERENCES binlog_events(evidence_id, source_file, log_position)
) STRICT;
```

An event that no marker claimed is still an event that exists in `binlog_events`, so this table is deliberately thin - it exists only to say "this event's `rule_id` for why it stayed ungrouped," everything else about the event is looked up through the FK.

### 12. coverage_reports and coverage_gaps

```sql
CREATE TABLE coverage_reports (
    coverage_report_id  TEXT PRIMARY KEY,
    case_id              TEXT NOT NULL REFERENCES cases(case_id),
    observed_files_json  TEXT NOT NULL CHECK (json_valid(observed_files_json)),
    inventory_id         TEXT REFERENCES binlog_inventory(inventory_id)
) STRICT;

CREATE TABLE coverage_gaps (
    coverage_gap_id     TEXT PRIMARY KEY,
    coverage_report_id  TEXT NOT NULL REFERENCES coverage_reports(coverage_report_id),
    reason              TEXT NOT NULL CHECK (reason IN ('missing_file', 'truncated_file', 'no_index')),
    rule_id             TEXT NOT NULL,
    after_file          TEXT,
    after_position      INTEGER,
    before_file         TEXT,
    missing_files_json  TEXT NOT NULL CHECK (json_valid(missing_files_json))
) STRICT;

CREATE INDEX idx_coverage_gaps_report ON coverage_gaps(coverage_report_id);
```

`CoverageReport` is produced once per grouping pass over a case's whole evidence set, so it gets a surrogate id rather than reusing `case_id` as the PK - a case could in principle be re-analysed and I did not want the schema itself to forbid keeping both runs. `coverage_gaps` is a real table rather than a JSON column on `coverage_reports` because `RecordHistory.coverage_gaps_touching` (§15) needs to reference individual gaps, not the report as a whole.

---

## State reconstruction (`StateReconstructionService`)

### 13. record_histories

```sql
CREATE TABLE record_histories (
    record_id                  TEXT PRIMARY KEY REFERENCES records(record_id),
    case_id                     TEXT NOT NULL REFERENCES cases(case_id),
    method                       TEXT NOT NULL CHECK (method IN (
                                    'primary_key_exact', 'composite_primary_key_exact',
                                    'primary_key_update_continuity', 'log_only_no_physical_counterpart',
                                    'physical_only_no_log_events', 'ambiguous',
                                    'table_has_no_primary_key', 'schema_not_available',
                                    'key_columns_not_in_row_image')),
    observed_values_json         TEXT NOT NULL CHECK (json_valid(observed_values_json)),
    partial_image_columns_json   TEXT NOT NULL CHECK (json_valid(partial_image_columns_json)),
    before_image_mismatch        INTEGER NOT NULL CHECK (before_image_mismatch IN (0, 1))
) STRICT;
```

`observed_values_json` is `Mapping[str, tuple[Value, ...]]` - a dict of columns to every value ever observed for that column - stored as `{"balance": [5000, 4000], ...}`. It is leaf data by Chethana's own rule (nothing downstream looks it up row-by-row, it is read whole per record), so it stays JSON even though it is one of the larger columns in this schema.

`method` is duplicated from `record_correlations.method` rather than joined, because `RecordHistory.method` is `MatchMethod` at the point reconstruction ran, and a report has to be able to show the history's own basis even if correlation is later re-run with a different result - copying it here is what stops one service's output from silently drifting when another's changes.

### 14. reconstructed_states

```sql
CREATE TABLE reconstructed_states (
    record_id          TEXT NOT NULL REFERENCES record_histories(record_id),
    state_kind         TEXT NOT NULL CHECK (state_kind IN ('earliest', 'final_log', 'speculative')),
    values_json        TEXT NOT NULL CHECK (json_valid(values_json)),
    presence           TEXT NOT NULL CHECK (presence IN ('present', 'absent', 'unknown')),
    derived_from_json  TEXT NOT NULL CHECK (json_valid(derived_from_json)),
    last_source_file   TEXT,
    last_log_position  INTEGER,
    PRIMARY KEY (record_id, state_kind)
) STRICT;
```

One row per state rather than three columns on `record_histories`, because `earliest_state`/`final_log_state`/`speculative_state` are the exact same shape (`ReconstructedState`) and three near-identical JSON columns would just be this table transposed, with no way to `CHECK` all three the same way. `values_json` holds `{"balance": 4000, "name": null}`, with columns the evidence never spoke to simply absent from the object - matching decision D in `docs/sqlite-schema.md`, `UNOBSERVED` never needs to appear inside this particular JSON because `ReconstructedState.value()` already treats a missing key as unobserved.

`derived_from_json` is `Mapping[str, EventRef]`, stored as `{"balance": ["mysql-bin.000006", 1112], ...}`. I did not turn this into a link table even though it references `binlog_events` rows, because - unlike `record_correlation_events` - nothing needs to query "which columns did this event derive," only the reverse ("what event produced this column's current value"), which is a read the JSON already answers directly.

### 15. history_steps

```sql
CREATE TABLE history_steps (
    record_id            TEXT NOT NULL REFERENCES record_histories(record_id),
    step_index           INTEGER NOT NULL,
    kind                  TEXT NOT NULL CHECK (kind IN (
                              'earliest_observed_state', 'event', 'rolled_back_event',
                              'uncommitted_event', 'identity_change', 'coverage_gap',
                              'physical_state')),
    durable               INTEGER NOT NULL CHECK (durable IN (0, 1)),
    rule_id               TEXT NOT NULL,
    presence_before       TEXT NOT NULL CHECK (presence_before IN ('present', 'absent', 'unknown')),
    presence_after        TEXT NOT NULL CHECK (presence_after IN ('present', 'absent', 'unknown')),
    changes_json          TEXT NOT NULL CHECK (json_valid(changes_json)),
    transaction_id        TEXT REFERENCES transactions(transaction_id),
    transaction_status    TEXT CHECK (transaction_status IS NULL OR
                              transaction_status IN ('committed', 'rolled_back', 'incomplete')),
    source_file           TEXT,
    log_position          INTEGER,
    timestamp             TEXT,
    PRIMARY KEY (record_id, step_index)
) STRICT;
```

`(record_id, step_index)` as the PK, mirroring `schema_columns`' `(schema_id, position)` - the whole point of a history is that its steps are ordered, and this makes "give me step 4 of this record's history" a direct index hit rather than a JSON array walk.

`changes_json` is `tuple[FieldChange, ...]` as a JSON array of `{"column", "before", "after", "changed"}` objects. This is the one place a list-of-structs stays JSON rather than becoming its own table: a `FieldChange` is not a reference to any other row, it is entirely self-contained data about one step, so there is nothing a `history_field_changes` table would let us `REFERENCES` that this does not already have.

`ref` (`EventRef | None`) is split into nullable `source_file`/`log_position` rather than a FK to `binlog_events`, unlike `record_correlation_events` - a `COVERAGE_GAP` or `EARLIEST_OBSERVED` step has no underlying binlog event at all, so the reference has to be optional, and SQLite cannot express "these two columns are a foreign key together, but only when both are non-null" as cleanly as it can express "no FK, just carry the pair."

### 16. record_history_coverage_gaps

```sql
CREATE TABLE record_history_coverage_gaps (
    record_id       TEXT NOT NULL REFERENCES record_histories(record_id),
    coverage_gap_id TEXT NOT NULL REFERENCES coverage_gaps(coverage_gap_id),
    PRIMARY KEY (record_id, coverage_gap_id)
) STRICT;
```

Backs `RecordHistory.coverage_gaps_touching`. This is the reason `coverage_gaps` (§12) needed its own surrogate id instead of just living as JSON inside `coverage_reports`.

---

## Reconciliation (`ReconciliationService`)

### 17. record_reconciliations

```sql
CREATE TABLE record_reconciliations (
    record_id       TEXT PRIMARY KEY REFERENCES records(record_id),
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    rollup          TEXT NOT NULL CHECK (rollup IN
                        ('Exact', 'Strong', 'Partial', 'Conflicting', 'Unresolved', 'Unsupported')),
    rollup_rule_id  TEXT NOT NULL,
    rollup_label    TEXT NOT NULL,
    triggers_json   TEXT NOT NULL CHECK (json_valid(triggers_json))
) STRICT;
```

`triggers_json` is `tuple[tuple[str, ReconResult], ...]`, stored as `[["R-REC-004", "Conflicting"], ...]` - a list of pairs with nothing to key a table on, so JSON.

The six `ReconResult` values are spelled with the capitals the frontend uses (`'Exact'`, not `'exact'`), because `classification.py` says these strings are shared verbatim with `frontend/src/lib/correlation.ts` - lower-casing them here for schema-naming consistency would break that contract for no reason.

### 18. field_reconciliations

```sql
CREATE TABLE field_reconciliations (
    record_id       TEXT NOT NULL REFERENCES record_reconciliations(record_id),
    field           TEXT NOT NULL,
    log_json        TEXT NOT NULL CHECK (json_valid(log_json)),
    phys_json       TEXT NOT NULL CHECK (json_valid(phys_json)),
    log_display     TEXT NOT NULL,
    phys_display    TEXT NOT NULL,
    result          TEXT NOT NULL CHECK (result IN
                        ('Exact', 'Strong', 'Partial', 'Conflicting', 'Unresolved', 'Unsupported')),
    rule_id         TEXT NOT NULL,
    comparable      INTEGER NOT NULL CHECK (comparable IN (0, 1)),
    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),
    PRIMARY KEY (record_id, field)
) STRICT;

CREATE INDEX idx_field_reconciliations_result ON field_reconciliations(result);
```

`(record_id, field)` as the PK - a field is only ever reconciled once per record, and this is also literally the shape `ReconciliationResult.rows_for()` queries by.

`log_json`/`phys_json` hold one `Value` each, using `docs/sqlite-schema.md` decision D's `{"__undecodable__": "reason"}` marker for `UndecodableValue`, plus a new marker for `Unobserved` - `{"__unobserved__": true}` - since decision D only covered the one non-scalar case that existed when Chethana wrote it. See the new decision below.

`provenance_json` is `FieldProvenance` (`log: tuple[ProvenanceReference,...]`, `physical: ProvenanceReference | None`, `transaction_id: str | None`) as one JSON object, for the same reason `findings.provenance_json` is JSON and not a link table - it is cited, never queried across rows.

The index on `result` is there because "show every Conflicting or Unresolved field" is the query that drives the flagged-records view (`RecordReconciliation.flagged`).

---

## Design decisions (additional to `docs/sqlite-schema.md`)

**G. `Unobserved` gets its own JSON marker, `{"__unobserved__": true}`.** `docs/sqlite-schema.md` decision D covers `UndecodableValue` because that was the only non-scalar member of `Value` when Chethana wrote it. `values.py` draws a hard line between the two - "we read this column and could not decode it" (`UndecodableValue`, leads to `Unsupported`) versus "no evidence ever mentioned this column at all" (`Unobserved`, leads to `Unresolved`) - and collapsing them into one marker in storage would erase a distinction the domain layer works hard to keep. Both markers are safe for the same reason decision D gives: MySQL column values are always scalars, so a dict where a value belongs can only be one of ours.

**H. Domain-derived tables carry `case_id`, not `tool_run_id`.** Every table in `docs/sqlite-schema.md` traces a value back to the one external command that produced it. Nothing here was produced by an external command - `record_correlations`, `record_histories` and `record_reconciliations` are conclusions my own code drew from rows already in this database, and their real provenance is the chain of foreign keys down to `binlog_events`/`physical_records`/`tool_runs`, not a `tool_run_id` of their own. `case_id` is what these tables need instead, since a correlation/reconstruction/reconciliation pass runs over a whole case's evidence at once rather than one file.

**I. One-to-one link tables (`record_physical_matches`, `record_identity_aliases`, `record_correlation_transactions`) stay separate rather than merging into one polymorphic "record links" table.** Each points at a different target table (`physical_records`, `records`, `transactions`), and a single merged table would need a `target_kind` column and lose real `REFERENCES` enforcement on every row - the same tradeoff `docs/sqlite-schema.md` already declines for `findings`.

---

## TODO

- Confirm the `physical_records.record_id` and `transactions` amendments (§7, §10) with Chethana before I write the migration, since they touch her tables.
- Check whether the frontend's correlation graph (`CorrelationEdge`) needs a materialised table once real data volumes are in, or whether the join in §9 stays fast enough.
