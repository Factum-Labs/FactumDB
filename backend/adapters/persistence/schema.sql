-- FactumDB case database schema.
-- Generated from docs/sqlite-schema.md - that document explains why each
-- table and column exists. This file is the executable copy, and is the
-- one the code actually runs.

CREATE TABLE IF NOT EXISTS cases (
    case_id        TEXT PRIMARY KEY,
    case_name      TEXT NOT NULL,
    examiner       TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at     TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS evidence_files (
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

CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence_files(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence_files(case_id, source_path);
CREATE TABLE IF NOT EXISTS tool_runs (
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

CREATE INDEX IF NOT EXISTS idx_tool_runs_evidence ON tool_runs(evidence_id);
CREATE TABLE IF NOT EXISTS schemas (
    schema_id        TEXT PRIMARY KEY,
    evidence_id      TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id      TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    database_name    TEXT NOT NULL,
    table_name       TEXT NOT NULL,
    mysql_version_id INTEGER NOT NULL,
    UNIQUE (evidence_id, database_name, table_name)
) STRICT;
CREATE TABLE IF NOT EXISTS schema_columns (
    schema_id      TEXT NOT NULL REFERENCES schemas(schema_id),
    position       INTEGER NOT NULL,
    name           TEXT NOT NULL,
    data_type      TEXT NOT NULL,
    is_nullable    INTEGER NOT NULL CHECK (is_nullable IN (0, 1)),
    is_primary_key INTEGER NOT NULL CHECK (is_primary_key IN (0, 1)),
    PRIMARY KEY (schema_id, position)
) STRICT;
CREATE TABLE IF NOT EXISTS physical_records (
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

CREATE INDEX IF NOT EXISTS idx_physical_table ON physical_records(database_name, table_name);
CREATE INDEX IF NOT EXISTS idx_physical_deleted ON physical_records(is_deleted);
CREATE TABLE IF NOT EXISTS binlog_events (
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

CREATE INDEX IF NOT EXISTS idx_binlog_table ON binlog_events(database_name, table_name);
CREATE INDEX IF NOT EXISTS idx_binlog_time  ON binlog_events(event_time_utc);
CREATE TABLE IF NOT EXISTS transactions (
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
CREATE TABLE IF NOT EXISTS transaction_events (
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
    event_id       TEXT NOT NULL REFERENCES binlog_events(event_id),
    event_order    INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, event_id)
) STRICT;
CREATE TABLE IF NOT EXISTS integrity_results (
    integrity_id     TEXT PRIMARY KEY,
    evidence_id      TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    tool_run_id      TEXT NOT NULL REFERENCES tool_runs(tool_run_id),
    total_pages      INTEGER,
    damaged_pages    INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('valid', 'damaged', 'unknown')),
    page_counts_json TEXT CHECK (page_counts_json IS NULL OR json_valid(page_counts_json)),
    raw_summary      TEXT
) STRICT;
CREATE TABLE IF NOT EXISTS warnings (
    warning_id   TEXT PRIMARY KEY,
    evidence_id  TEXT REFERENCES evidence_files(evidence_id),
    tool_run_id  TEXT REFERENCES tool_runs(tool_run_id),
    code         TEXT NOT NULL,
    message      TEXT NOT NULL,
    context_json TEXT CHECK (context_json IS NULL OR json_valid(context_json)),
    created_at   TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_warnings_code ON warnings(code);
CREATE TABLE IF NOT EXISTS binlog_inventory (
    inventory_id       TEXT PRIMARY KEY,
    evidence_id        TEXT NOT NULL REFERENCES evidence_files(evidence_id),
    index_file         TEXT NOT NULL,
    listed_files_json  TEXT NOT NULL CHECK (json_valid(listed_files_json)),
    present_files_json TEXT NOT NULL CHECK (json_valid(present_files_json)),
    missing_files_json TEXT NOT NULL CHECK (json_valid(missing_files_json))
) STRICT;
