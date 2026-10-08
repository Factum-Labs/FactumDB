# FactumDB SQLite Schema

## What this is

This is the internal store for one case. Everything the adapters extract goes in here, and Yasiru's domain services and the UI read it back out. The original evidence files are never stored inside the database - they stay in the case folder and we only keep their paths and hashes.

The tables map fairly directly onto the models in `canonical-model.md`. Where a model field is a dict or a list it is stored as a JSON column, which is explained in the decisions at the bottom.

Written against SQLite 3.46.1 (the version in Ubuntu 26.04).

## Opening the database

Two things have to be set on every connection, otherwise the schema does not actually do what it looks like it does:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
```

Foreign keys are **off by default** in SQLite. All the `REFERENCES` below are parsed and then ignored unless you turn them on, and it is per connection, not stored in the file. This is easy to miss - the schema looks correct but enforces nothing.

WAL mode just gives better behaviour when something reads while something else writes.

---

## 1. cases

```sql
CREATE TABLE cases (
    case_id        TEXT PRIMARY KEY,
    case_name      TEXT NOT NULL,
    examiner       TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at     TEXT NOT NULL
) STRICT;
```

The fields follow Nisal's `Case` model in `backend/core/domain/models/case.py`. The column names stay `case_id` and `case_name` rather than the model's `id` and `name`, because a bare `id` is ambiguous once several tables are joined. The mapping happens in the repository, which is what that layer is for.

`workspace_path` is the directory the case owns. Working copies and preserved raw output live under it, so the path belongs with the case rather than being recomputed.

---

## 2. evidence_files

```sql
CREATE TABLE evidence_files (
    evidence_id         TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(case_id),
    kind                TEXT NOT NULL CHECK (kind IN ('ibd', 'binlog', 'binlog_index')),
    filename            TEXT NOT NULL,
    source_path         TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    source_sha256       TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN
                            ('registered', 'verified', 'hash_mismatch')),
    working_copy_path   TEXT,
    working_copy_sha256 TEXT,
    acquisition_method  TEXT NOT NULL DEFAULT '',
    registered_at       TEXT NOT NULL
) STRICT;

CREATE INDEX idx_evidence_case ON evidence_files(case_id);
CREATE INDEX idx_evidence_source ON evidence_files(case_id, source_path);
```

Both hashes are stored because the point of a working copy is proving it is identical to the original before anything is run against it. If `source_sha256` and `working_copy_sha256` ever differ, the copy is not a faithful reproduction and nothing extracted from it can be relied on.

The working copy columns are nullable because of when the row is written. A file is registered and hashed first, and only then copied, so at registration there is no working copy to record. A null is the honest answer there, and `verification_status` says which stage the file has reached - `registered`, `verified`, or `hash_mismatch`.

`binlog_index` is in the type list because of `mysql-bin.index`. It is not a log itself but it is evidence, since it is how we find out a log file is missing.

`acquisition_method` records how the file was taken, for example "FLUSH TABLES FOR EXPORT + cp". That matters because it is what shows the page image is internally consistent rather than copied while the server was mid-write, so the method is part of the evidence rather than a footnote.

---

## 3. tool_runs

```sql
CREATE TABLE tool_runs (
    tool_run_id       TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES cases(case_id),
    evidence_id       TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_name         TEXT NOT NULL CHECK (tool_name IN
                          ('ibd2sdi', 'innochecksum', 'ibd2sql', 'mysqlbinlog')),
    tool_version      TEXT NOT NULL,
    executable_path   TEXT NOT NULL,
    executable_sha256 TEXT NOT NULL,
    arguments_json    TEXT NOT NULL CHECK (json_valid(arguments_json)),
    status            TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    exit_code         INTEGER,
    stdout_path       TEXT,
    stdout_sha256     TEXT,
    stdout_size_bytes INTEGER,
    stderr_path       TEXT,
    stderr_sha256     TEXT,
    stderr_size_bytes INTEGER
) STRICT;

CREATE INDEX idx_tool_runs_evidence ON tool_runs(evidence_id);
CREATE INDEX idx_tool_runs_case ON tool_runs(case_id);
```

This is the most important table in the schema. Almost every other table has a `tool_run_id`, so any value we show in a report can be traced back to the exact command that produced it. That is the whole "how do you know that?" requirement.

`tool_version` matters because these tools change their output format between versions. It is read from the tool's own `--version` the first time each tool runs, not written into configuration, because a system update can change it without anything in the project changing - the MySQL utilities here went from 8.4.10 to 8.4.11 that way. The MySQL tools print `innochecksum  Ver 8.4.11-0ubuntu0.26.04.1 for Linux...` and only the part after `Ver` is kept. `ibd2sql` prints `ibd2sql v2.3-20260526`, which is kept as printed.

`executable_path` and `executable_sha256` identify the binary itself. A version string can be shared by several builds; a hash of the file cannot, so the claim is about one specific executable rather than a label. For `ibd2sql`, which is a Python script, the executable recorded is `main.py`, not `python3`. Hashing the interpreter would say which Python ran, not which `ibd2sql` produced the rows.

`arguments_json` holds the arguments as a JSON array instead of one command string. Re-joining arguments into a line loses the boundary between them as soon as a path contains a space, and then it is no longer possible to say exactly what was run.

`stdout` and `stderr` are recorded separately, each with its own path, hash and size. Both are needed: `innochecksum` reports a damaged page on stderr, so keeping only stdout would record an empty success for a file the tool had just called invalid.

The index is on `evidence_id` because "show me every tool run for this file" is the query the UI will use most. The one on `case_id` is for listing a whole case's runs, which the case export does.

---

## 4. schemas

```sql
CREATE TABLE schemas (
    schema_id        TEXT PRIMARY KEY,
    evidence_id      TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id      TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    database_name    TEXT NOT NULL,
    table_name       TEXT NOT NULL,
    mysql_version_id INTEGER NOT NULL,
    UNIQUE (evidence_id, database_name, table_name)
) STRICT;
```

The `UNIQUE` stops us storing the same table's schema twice for one evidence file, which would happen if someone ran the extraction stage twice.

`mysql_version_id` is `NOT NULL` because the `Schema` model requires it. `ibd2sdi` always reports it, and a schema we could not place to a MySQL version is not one we should be trusting output from.

---

## 5. schema_columns

```sql
CREATE TABLE schema_columns (
    schema_id      TEXT NOT NULL REFERENCES schemas(schema_id),
    position       INTEGER NOT NULL,
    name           TEXT NOT NULL,
    data_type      TEXT NOT NULL,
    is_nullable    INTEGER NOT NULL CHECK (is_nullable IN (0, 1)),
    is_primary_key INTEGER NOT NULL CHECK (is_primary_key IN (0, 1)),
    PRIMARY KEY (schema_id, position)
) STRICT;
```

This is a real table instead of a JSON column inside `schemas`, unlike the other list-type fields. The reason is that this is the one lookup that happens constantly: every single binlog row event needs to turn `@1`, `@2`, `@3` into column names. Making `(schema_id, position)` the primary key means that lookup is a direct index hit rather than parsing JSON every time.

SQLite has no boolean type, so the two flags are integers with a `CHECK` limiting them to 0 or 1. Without the check you could store 7 in `is_nullable`.

---

## 6. physical_records

```sql
CREATE TABLE physical_records (
    record_id     TEXT PRIMARY KEY,
    evidence_id   TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id   TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    database_name TEXT NOT NULL,
    table_name    TEXT NOT NULL,
    values_json   TEXT NOT NULL CHECK (json_valid(values_json)),
    is_deleted    INTEGER NOT NULL CHECK (is_deleted IN (0, 1)),
    page_no       INTEGER,
    page_offset   INTEGER
) STRICT;

CREATE INDEX idx_physical_table ON physical_records(database_name, table_name);
CREATE INDEX idx_physical_deleted ON physical_records(is_deleted);
CREATE INDEX idx_physical_evidence
    ON physical_records(evidence_id, database_name, table_name);
```

`page_no` and `page_offset` are nullable because we might not always be able to work them out, and a null is honest about that. In the scenario 2 evidence the deleted row is at page 4, offset 170.

The index on `is_deleted` is there because "show me all recovered deleted rows" is going to be one of the main things an investigator asks for, and it is also one of the main screens to demonstrate.

`idx_physical_evidence` is for reading one case's rows of one table, which goes through the case's evidence files (decision G).

---

## 7. binlog_events

```sql
CREATE TABLE binlog_events (
    event_id       TEXT PRIMARY KEY,
    evidence_id    TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id    TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    event_type     TEXT NOT NULL CHECK (event_type IN ('INSERT', 'UPDATE', 'DELETE')),
    database_name  TEXT NOT NULL,
    table_name     TEXT NOT NULL,
    before_json    TEXT CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json     TEXT CHECK (after_json IS NULL OR json_valid(after_json)),
    event_time_utc TEXT,
    raw_timestamp  TEXT,
    gtid           TEXT,
    thread_id      INTEGER,
    source_file    TEXT NOT NULL,
    log_position   INTEGER NOT NULL,
    row_index      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (evidence_id, source_file, log_position, row_index)
) STRICT;

CREATE INDEX idx_binlog_table ON binlog_events(database_name, table_name);
CREATE INDEX idx_binlog_time  ON binlog_events(event_time_utc);
```

`before_json` and `after_json` are nullable on purpose, because an INSERT has no before image and a DELETE has no after image. That is the `None` rule from the canonical model.

The `UNIQUE` needs care. `log_position` is not unique on its own - every binlog file starts its positions again at 4, so `mysql-bin.000001` and `mysql-bin.000006` can both have a position 1112. The unique key has to be the file **and** the position together. Making `log_position` unique by itself would cause the second binlog file to fail to load.

The file and position together are still not enough, because one binlog event can carry several rows. A statement like `UPDATE accounts SET status = 'frozen' WHERE balance > 3000` that changes two rows is written as a single `Update_rows` event with two row images, and both share the event's `end_log_pos`. `row_index` is the position of a row image within its event - 0 for the first, 1 for the second - and it is part of the unique key so those rows stay distinct.

This was found by feeding a two-row event through the adapter: it produced two row changes at the same position. Without `row_index` the second one is rejected by the unique constraint, or, with `INSERT OR REPLACE`, silently overwrites the first one with no error at all. None of the original test scenarios hit this because each of their statements changed a single row.

`row_index` defaults to 0, so a single-row event - which is most of them - has the same identity it always had.

`source_file` is the binlog's own name, `mysql-bin.000006`, as it was registered - the same name in `transactions`. The adapter reads a working copy, which the filesystem layer names `<evidence id>-mysql-bin.000006`, so the decode is stored under the registered name instead. The domain orders the logs by finding these names in `mysql-bin.index`; with the working-copy names it found none of them and fell back to ordering by evidence id, which put the logs in the wrong order.

`event_time_utc` is indexed because building a timeline means sorting by time, and that is the main thing this tool does.

---

## 8. transactions

```sql
CREATE TABLE transactions (
    transaction_id TEXT PRIMARY KEY,
    evidence_id    TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id    TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    gtid           TEXT,
    xid            INTEGER,
    thread_id      INTEGER,
    status         TEXT NOT NULL CHECK (status IN ('committed', 'rolled_back', 'incomplete')),
    source_file    TEXT NOT NULL,
    start_position INTEGER NOT NULL,
    end_position   INTEGER NOT NULL
) STRICT;

CREATE INDEX idx_transactions_evidence ON transactions(evidence_id, source_file);
```

`gtid` and `xid` are both nullable because a server can be running without GTID enabled. We record what is there and do not invent the rest.

The index serves reading a case's markers and replacing one binlog file's markers when it is decoded again.

---

## 9. transaction_events

```sql
CREATE TABLE transaction_events (
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
    event_id       TEXT NOT NULL REFERENCES binlog_events(event_id),
    event_order    INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, event_id)
) STRICT;

CREATE INDEX idx_transaction_events_event ON transaction_events(event_id);
```

This one is not in the model list - it is added because `TransactionMarker.event_positions` is a list, and a list of things that already exist as rows should be a link table rather than a JSON blob. This way the foreign key actually checks that the event exists, which a JSON array of numbers could never do.

`event_order` keeps the original order of the events inside the transaction, because the order matters when the domain layer replays them.

A marker lists log positions, but since `row_index` was added one position can be several rows in `binlog_events` (a multi-row UPDATE or DELETE). Every row at the position is linked, and they share the position's `event_order`. Reading the marker back takes each position once, so `event_positions` comes back exactly as the adapter produced it.

The events have to be saved before the markers. If a marker points at a position with no stored event, the foreign key rejects it, which is the point: a transaction claiming an event we do not have is a gap that should be noticed, not a dangling number.

The primary key starts with `transaction_id`, so it cannot find the links of one event. That lookup happens for every event deleted when a binlog is decoded again, because the foreign key check has to confirm nothing still points at it, and without `idx_transaction_events_event` each check read the whole table. With 60,000 events, decoding the file again took 8.9 s without the index and 1.1 s with it.

---

## 10. integrity_results

```sql
CREATE TABLE integrity_results (
    integrity_id     TEXT PRIMARY KEY,
    evidence_id      TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id      TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    total_pages      INTEGER,
    damaged_pages    INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('valid', 'damaged', 'unknown')),
    page_counts_json TEXT CHECK (page_counts_json IS NULL OR json_valid(page_counts_json)),
    raw_summary      TEXT
) STRICT;

CREATE INDEX idx_integrity_evidence ON integrity_results(evidence_id);
```

`page_counts_json` holds the full page type breakdown from `innochecksum -S`, including the ones that are zero. In the first evidence set `Undo log page` is 0, and that zero is the reason the original balance of 5000 cannot be recovered from the `.ibd` file at all. It would be easy to drop zeros as noise but that would throw away the finding.

There is no table name in this table because `innochecksum` does not know about tables, only pages. `integrity_for(database, table)` finds the right row by joining through `schemas` on `evidence_id`, since the schema extracted from an `.ibd` says which table that file holds. So an integrity result can only be found by table once that file's schema has been extracted.

---

## 11. warnings

```sql
CREATE TABLE warnings (
    warning_id   TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES cases(case_id),
    evidence_id  TEXT REFERENCES evidence_files(evidence_id),
    tool_run_id  TEXT REFERENCES tool_runs(tool_run_id),
    code         TEXT NOT NULL,
    message      TEXT NOT NULL,
    context_json TEXT CHECK (context_json IS NULL OR json_valid(context_json)),
    created_at   TEXT NOT NULL
) STRICT;

CREATE INDEX idx_warnings_code ON warnings(case_id, code);
```

`evidence_id` and `tool_run_id` are nullable here, unlike everywhere else, because some warnings are about the case in general rather than one specific file or one specific tool run.

`case_id` is required for the same reason. Every other table reaches its case through `evidence_id`, but a case-level warning has no evidence file to go through, so without its own `case_id` it would belong to no case at all and `list_by_case` could never find it.

---

## 12. binlog_inventory

```sql
CREATE TABLE binlog_inventory (
    inventory_id       TEXT PRIMARY KEY,
    evidence_id        TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    index_file         TEXT NOT NULL,
    listed_files_json  TEXT NOT NULL CHECK (json_valid(listed_files_json)),
    present_files_json TEXT NOT NULL CHECK (json_valid(present_files_json)),
    missing_files_json TEXT NOT NULL CHECK (json_valid(missing_files_json))
) STRICT;

CREATE INDEX idx_inventory_evidence ON binlog_inventory(evidence_id);
```

`missing_files_json` is worked out when we save, not calculated every time it is read, because it is what decides whether a mismatch gets reported as an evidence gap or as tampering. Storing it means the report and the screen can never disagree.

Reminder from the model doc: `mysql-bin.index` stores absolute paths like `/var/log/mysql/mysql-bin.000006`, so the comparison has to be on file names only.

The inventory is recorded at the start of the binlog decoding stage, before any log is decoded, by reading the registered `mysql-bin.index` (`adapters/tools/binlog_index.py`). `listed` is what the index says the server had; `present` is the binlog files registered in the case. If no index was seized, nothing is recorded and the analysis reports binlog coverage as unknown (R-COV-001) - never as complete. There is no `tool_run_id` here because no external tool is run: the index is registered evidence with its own hash, and that is what ties the inventory to the file it was read from.

---

## 13. case_scopes

```sql
CREATE TABLE case_scopes (
    case_id    TEXT PRIMARY KEY REFERENCES cases(case_id),
    scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
    updated_at TEXT NOT NULL
) STRICT;
```

The databases and tables the investigator wants the analysis to cover, for example `{"databases": [], "tables": [["finance", "accounts"]]}`. A name under `databases` brings in every table of that database. No row means everything is in scope.

This is the database and table filtering from the week 4 plan. It filters what the analysis **looks at**, never what is **stored**: every row and event extracted stays in its table whatever the scope, so a narrow scope can always be widened again without extracting anything twice. Filtering at extraction time instead (for example `mysqlbinlog --database`) would throw evidence away before anyone had looked at it.

A case has one scope, and saving a new one replaces it. It is a setting, not evidence - what each analysis actually used is kept in `normalizations`.

---

## 14. normalizations

```sql
CREATE TABLE normalizations (
    case_id       TEXT PRIMARY KEY REFERENCES cases(case_id),
    scope_json    TEXT NOT NULL CHECK (json_valid(scope_json)),
    counts_json   TEXT NOT NULL CHECK (json_valid(counts_json)),
    normalized_at TEXT NOT NULL
) STRICT;
```

The normalization stage does not copy the canonical data again. The extraction stages already stored it, and two copies could drift apart. What normalization adds is a decision - which part of the stored evidence the analysis covers - and this table records it:

- `scope_json` is a copy of the scope that was used, not a link to `case_scopes`, so changing the scope later cannot rewrite what an earlier analysis was based on.
- `counts_json` holds, for each kind of evidence, how much was in scope out of how much is stored, for example `{"events": [2, 5], ...}`. That is what lets a report say "2 of 5 events were in scope" rather than leaving the reader to wonder whether anything was left out.

Saving refuses counts larger than what the database stores, since normalized evidence like that cannot have come from this case.

The scope is applied to every kind of evidence the same way. Filtering a table's rows but not its binlog events would show the domain services events for a table with no tablespace, and they would report "we were not given the file" about a file we do have. A transaction that touched tables inside and outside the scope keeps only its in-scope events, one with no in-scope events is left out, and one that listed no events at all is kept, because nothing in it says which tables it was about.

---

## 15. analysis_results

```sql
CREATE TABLE analysis_results (
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    stage       TEXT NOT NULL CHECK (stage IN
                    ('grouping', 'correlation', 'reconstruction', 'reconciliation')),
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    saved_at    TEXT NOT NULL,
    PRIMARY KEY (case_id, stage)
) STRICT;
```

The four results of Yasiru's domain services, one JSON document per case and stage. His `correlation-engine-output-schema.md` describes a fully relational design instead, which would let single findings be queried in SQL. The UI reads results through the sidecar, which loads a whole result at a time anyway, so one document per stage does the job for now. Tables can replace it later without changing the `DomainRepository` interface.

The round trip has to be exact, because each stage reads the previous stage's result back from here. Column values keep the tags from decision D, so a `Decimal` cannot come back as a string, and everything else is rebuilt from the type hints of the dataclass it belongs to (`_results.py`). All 48 results from Yasiru's 12 golden datasets load back equal, with the same type at every level - which matters because his enums are `StrEnum`s and would compare equal to plain strings.

The results build on each other, so saving one stage deletes the stages after it, and normalizing the case again deletes all of them. A later stage can then never load a result made from an older version of an earlier one: it finds nothing, and the use case says which stage has to run first.

---

## 16. reports

```sql
CREATE TABLE reports (
    report_id   TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    format      TEXT NOT NULL CHECK (format IN ('json', 'csv', 'html', 'pdf')),
    version     INTEGER NOT NULL CHECK (version >= 1),
    location    TEXT NOT NULL,
    files_json  TEXT NOT NULL CHECK (json_valid(files_json)),
    analysed_at TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (case_id, format, version)
) STRICT;
```

The report metadata: one row for every report or export made from a case. The project proposal promises "maintaining different versions of reports", and a case is often reported on more than once - before and after more evidence arrives, or after the analysis is run again.

- `version` counts up separately for each format, so "the third JSON export of this case" means one thing. `report_id` is `<case>:<format>:v<version>`.
- `files_json` lists every file written, each with its SHA-256 and size: one file for JSON or PDF, the whole folder for CSV. Anyone holding a copy can check it is the file FactumDB wrote by running `sha256sum` - no need to trust the tool for that.
- `analysed_at` is the `saved_at` of the case's reconciliation result when the report was made, or empty if the analysis had not run. A report made before the analysis was run again shows that it describes the older analysis.

The JSON and CSV exports record themselves (`case_export.py`). A PDF or HTML report can call `SqliteReportRepository.record()` once its file is written. The table is not part of the export itself, so exporting the same case twice still gives the same content.

---

## Design decisions

**A. IDs are text, not auto-increment integers.** Nisal's `Case` model already generates a UUID string for `case_id`, so the same style is used everywhere rather than having two different kinds of ID in one database. Consistency across the team is worth more here than the small speed difference.

**B. Timestamps are TEXT in ISO-8601 UTC**, for example `2026-08-15T19:06:25.000000Z`. SQLite has no date type at all, so the choice is text or a number. Text sorts correctly, and someone opening the database directly can read it, which matters when the point of the tool is showing your working.

The microseconds are always written, even when they are zero. Text only sorts in time order if every value has the same layout: `19:06:25.500000Z` would otherwise sort before `19:06:25Z`, because `.` comes before `Z`.

**C. Dict and list fields are stored as JSON columns**, except where a real table is clearly better. Row values, page counts and the file lists are JSON. Schema columns and transaction events are real tables, because those two get looked up constantly and need foreign keys. A fully normalised design (one row per column value) would be more "correct" but it is a lot more work, and the project runs to 8 weeks, so the simpler design is used and the tradeoff documented.

**D. Undecodable values are stored inside the JSON as `{"__undecodable__": "reason"}`.** This is safe because MySQL column values are always scalars - a number, a string, a date, or NULL. They are never dictionaries. So any dict appearing where a value should be can only be our marker, and it can never collide with real data.

**E. Every table that holds extracted data has a `tool_run_id`.** That is what makes the provenance requirement actually true rather than just something we say in the report. When rows are read for the analysis, each one comes back with a `ProvenanceReference` rebuilt from its `evidence_id`, `tool_run_id` and the run's tool name (`_provenance.py`), so the findings the domain services make can point to the run behind them. It is rebuilt on every read rather than stored twice, so it can never disagree with the row.

**F. `STRICT` on every table.** Normally SQLite lets you put a string into an INTEGER column and says nothing. For a forensic tool that silently storing the wrong type is a bad failure mode, so `STRICT` turns it into an error instead.

**G. Every read for one case goes through that case's evidence files.** The extracted rows have no `case_id` of their own; they reach their case through `evidence_id`. So the normalizer, the evidence handed to the analysis and the decoder's schema lookup only keep rows whose evidence file belongs to the case (`_in_case.py`). That keeps two cases in one database file apart even when they have a table with the same name, a binlog with the same name and events at the same positions. Without it the newest schema of a table was used for every case, and one case's analysis read the other case's rows. Read methods that are given no case still cover the whole database. The indexes added for these reads are checked by `test_sqlite_indexes.py`, which fails if any statement run on a case makes SQLite read a whole table.

---

## TODO

- Agree decision D with Nisal since he owns the storage side of the pipeline.
- Check with Yasiru whether the domain services need anything from `transaction_events` that is not there yet.
- If the UI needs to query single findings or record histories in SQL, replace the JSON documents in `analysis_results` with tables following `correlation-engine-output-schema.md`.
