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
    case_id    TEXT PRIMARY KEY,
    case_name  TEXT NOT NULL,
    examiner   TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
```

The fields match Nisal's `Case` model in `backend/core/domain/models/case.py` exactly, so the repository can map straight across without renaming anything.

---

## 2. evidence_files

```sql
CREATE TABLE evidence_files (
    evidence_id       TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES cases(case_id),
    evidence_type     TEXT NOT NULL CHECK (evidence_type IN ('ibd', 'binlog', 'binlog_index')),
    file_name         TEXT NOT NULL,
    original_path     TEXT NOT NULL,
    size_bytes        INTEGER NOT NULL,
    sha256_original   TEXT NOT NULL,
    working_copy_path TEXT NOT NULL,
    sha256_working    TEXT NOT NULL,
    registered_at     TEXT NOT NULL,
    acquisition_method TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE INDEX idx_evidence_case ON evidence_files(case_id);
```

We store both hashes because the point of a working copy is that you prove it is identical to the original before you run anything on it. If the two hashes ever differ, that evidence is not usable and the tool has to say so.

`binlog_index` is in the type list because of `mysql-bin.index`. It is not a log itself but it is evidence, since it is how we find out a log file is missing.

`acquisition_method` records how the file was taken, for example "FLUSH TABLES FOR EXPORT + cp". That matters because it is what shows the page image is internally consistent rather than copied while the server was mid-write, so the method is part of the evidence rather than a footnote.

---

## 3. tool_runs

```sql
CREATE TABLE tool_runs (
    tool_run_id       TEXT PRIMARY KEY,
    evidence_id       TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_name         TEXT NOT NULL CHECK (tool_name IN ('ibd2sdi', 'innochecksum', 'ibd2sql', 'mysqlbinlog')),
    tool_version      TEXT,
    command           TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    exit_code         INTEGER,
    raw_output_path   TEXT,
    raw_output_sha256 TEXT
) STRICT;

CREATE INDEX idx_tool_runs_evidence ON tool_runs(evidence_id);
```

This is the most important table in the schema. Almost every other table has a `tool_run_id`, so any value we show in a report can be traced back to the exact command that produced it. That is the whole "how do you know that?" requirement.

`tool_version` matters because these tools change their output format between versions. Three of them have a `--version` flag. `ibd2sql` does not have one at all, so for that one `git describe --tags` inside its clone is used, which gives something like `v2.3-3-g62b7db5`. That is actually better than a version number because it points at one exact commit.

The index is on `evidence_id` because "show me every tool run for this file" is the query the UI will use most.

---

## 4. schemas

```sql
CREATE TABLE schemas (
    schema_id        TEXT PRIMARY KEY,
    evidence_id      TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id      TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    database_name    TEXT NOT NULL,
    table_name       TEXT NOT NULL,
    mysql_version_id INTEGER,
    UNIQUE (evidence_id, database_name, table_name)
) STRICT;
```

The `UNIQUE` stops us storing the same table's schema twice for one evidence file, which would happen if someone ran the extraction stage twice.

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
```

`page_no` and `page_offset` are nullable because we might not always be able to work them out, and a null is honest about that. In the scenario 2 evidence the deleted row is at page 4, offset 170.

The index on `is_deleted` is there because "show me all recovered deleted rows" is going to be one of the main things an investigator asks for, and it is also one of the main screens to demonstrate.

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
    UNIQUE (evidence_id, source_file, log_position)
) STRICT;

CREATE INDEX idx_binlog_table ON binlog_events(database_name, table_name);
CREATE INDEX idx_binlog_time  ON binlog_events(event_time_utc);
```

`before_json` and `after_json` are nullable on purpose, because an INSERT has no before image and a DELETE has no after image. That is the `None` rule from the canonical model.

The `UNIQUE` needs care. `log_position` is not unique on its own - every binlog file starts its positions again at 4, so `mysql-bin.000001` and `mysql-bin.000006` can both have a position 1112. The unique key has to be the file **and** the position together. Making `log_position` unique by itself would cause the second binlog file to fail to load.

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
```

`gtid` and `xid` are both nullable because a server can be running without GTID enabled. We record what is there and do not invent the rest.

---

## 9. transaction_events

```sql
CREATE TABLE transaction_events (
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
    event_id       TEXT NOT NULL REFERENCES binlog_events(event_id),
    event_order    INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, event_id)
) STRICT;
```

This one is not in the model list - it is added because `TransactionMarker.event_positions` is a list, and a list of things that already exist as rows should be a link table rather than a JSON blob. This way the foreign key actually checks that the event exists, which a JSON array of numbers could never do.

`event_order` keeps the original order of the events inside the transaction, because the order matters when the domain layer replays them.

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
```

`page_counts_json` holds the full page type breakdown from `innochecksum -S`, including the ones that are zero. In the first evidence set `Undo log page` is 0, and that zero is the reason the original balance of 5000 cannot be recovered from the `.ibd` file at all. It would be easy to drop zeros as noise but that would throw away the finding.

---

## 11. warnings

```sql
CREATE TABLE warnings (
    warning_id   TEXT PRIMARY KEY,
    evidence_id  TEXT REFERENCES evidence_files(evidence_id),
    tool_run_id  TEXT REFERENCES tool_runs(tool_run_id),
    code         TEXT NOT NULL,
    message      TEXT NOT NULL,
    context_json TEXT CHECK (context_json IS NULL OR json_valid(context_json)),
    created_at   TEXT NOT NULL
) STRICT;

CREATE INDEX idx_warnings_code ON warnings(code);
```

The two foreign keys are nullable here, unlike everywhere else, because some warnings are about the case in general rather than one specific file or one specific tool run.

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
```

`missing_files_json` is worked out when we save, not calculated every time it is read, because it is what decides whether a mismatch gets reported as an evidence gap or as tampering. Storing it means the report and the screen can never disagree.

Reminder from the model doc: `mysql-bin.index` stores absolute paths like `/var/log/mysql/mysql-bin.000006`, so the comparison has to be on file names only.

---

## Design decisions

**A. IDs are text, not auto-increment integers.** Nisal's `Case` model already generates a UUID string for `case_id`, so the same style is used everywhere rather than having two different kinds of ID in one database. Consistency across the team is worth more here than the small speed difference.

**B. Timestamps are TEXT in ISO-8601 UTC**, for example `2026-08-15T19:06:25Z`. SQLite has no date type at all, so the choice is text or a number. Text sorts correctly, and someone opening the database directly can read it, which matters when the point of the tool is showing your working.

**C. Dict and list fields are stored as JSON columns**, except where a real table is clearly better. Row values, page counts and the file lists are JSON. Schema columns and transaction events are real tables, because those two get looked up constantly and need foreign keys. A fully normalised design (one row per column value) would be more "correct" but it is a lot more work, and the project runs to 8 weeks, so the simpler design is used and the tradeoff documented.

**D. Undecodable values are stored inside the JSON as `{"__undecodable__": "reason"}`.** This is safe because MySQL column values are always scalars - a number, a string, a date, or NULL. They are never dictionaries. So any dict appearing where a value should be can only be our marker, and it can never collide with real data.

**E. Every table that holds extracted data has a `tool_run_id`.** That is what makes the provenance requirement actually true rather than just something we say in the report.

**F. `STRICT` on every table.** Normally SQLite lets you put a string into an INTEGER column and says nothing. For a forensic tool that silently storing the wrong type is a bad failure mode, so `STRICT` turns it into an error instead.

---

## TODO

- Agree decision D with Nisal since he owns the storage side of the pipeline.
- Check with Yasiru whether the domain services need anything from `transaction_events` that is not there yet.
- The tables for correlation results, record histories and reconciliation results are not here yet. Those come out of Yasiru's domain services in weeks 5 and 6, so they will be added once their shape is known.
