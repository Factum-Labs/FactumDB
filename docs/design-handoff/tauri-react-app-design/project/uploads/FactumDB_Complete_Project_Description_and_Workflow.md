# FactumDB Project Description and End-to-End Workflow

## 1. Project Overview

**FactumDB** is a forensically sound, investigator-facing Linux desktop application for correlating MySQL InnoDB table records with row-based MySQL binary-log events.

The tool is designed for cases where an investigator has separate MySQL evidence artefacts, mainly:

- one or more file-per-table `.ibd` files; and
- one or more MySQL row-based binary-log files.

These artefacts provide different views of database activity:

- the `.ibd` file represents the physical table state available in the acquired tablespace; and
- the binary logs represent historical row events such as inserts, updates, deletes, transaction boundaries, and commit information.

Existing utilities can extract useful information from these files, but their outputs are separate and usually require manual interpretation. FactumDB integrates those outputs into one traceable workflow that reconstructs record histories, groups related events into transactions, compares reconstructed states with physical table records, identifies evidence gaps or conflicts, and produces investigator-readable reports.

FactumDB is not intended to replace the underlying extraction utilities. Its main contribution is the forensic correlation, reconstruction, reconciliation, visualization, provenance, and reporting layer built above them.

---

## 2. Problem Addressed

During a MySQL investigation, an analyst may receive:

```text
finance/accounts.ibd
finance/transactions.ibd
binlog.000018
binlog.000019
binlog.000020
```

The `.ibd` files may contain current or recoverable table records, while the binary logs may contain a historical sequence of row changes. However, these sources are not automatically connected.

An analyst may need to determine:

- which binary-log events belong to a particular table;
- which events affected a particular logical record;
- which events belong to the same committed transaction;
- how a record changed over time;
- whether the log-derived final state agrees with the physical table state;
- whether a deletion event is supported by the available physical evidence;
- whether a missing log file creates an incomplete timeline;
- whether a schema mismatch prevents safe interpretation; and
- whether a finding can be traced back to its original evidence source.

Without an integrated tool, the analyst may have to use multiple command-line utilities, inspect large outputs, manually map positional fields such as `@1`, `@2`, and `@3` to schema columns, follow transaction boundaries, match primary keys, replay changes, and prepare a report manually.

FactumDB addresses this workflow gap.

---

## 3. Main Objective

The main objective is to design and implement a forensically sound tool that correlates records extracted from MySQL InnoDB tablespace files with row-based binary-log events in order to:

- reconstruct record histories;
- group related changes into transactions;
- compare log-derived states with physical database records;
- detect missing, conflicting, ambiguous, or unsupported evidence; and
- present the results in a form suitable for examiner review.

---

## 4. Core Functions

### 4.1 Evidence Intake

The examiner creates a case and imports the available evidence files.

The tool records:

- case identifier;
- evidence filename;
- evidence type;
- file size;
- acquisition or import time;
- SHA-256 hash;
- processing status; and
- relevant examiner notes.

### 4.2 Read-Only Evidence Handling

Original evidence files are not processed directly after intake.

The tool:

1. calculates a SHA-256 hash of each original file;
2. creates a controlled working copy;
3. hashes the working copy;
4. verifies that the original and working-copy hashes match; and
5. performs all extraction and analysis on the verified working copy.

This protects the original evidence from accidental modification.

### 4.3 External Utility Orchestration

FactumDB will programmatically run the following utilities against verified working copies:

- `ibd2sdi` for schema metadata;
- `innochecksum` for InnoDB page-integrity checking;
- `ibd2sql` for row extraction from `.ibd` files; and
- `mysqlbinlog` for decoding row-based binary-log events.

For each execution, the tool records the exact command line, executable path and version, input file, timestamps, outputs, errors, exit status, and generated artefacts.

### 4.4 Normalization

The raw outputs of the external utilities use different structures and formats. FactumDB converts them into a canonical internal representation.

The normalized model may include:

- cases;
- evidence files;
- database schemas;
- tables and columns;
- physical records;
- binary-log events;
- transaction boundaries and identifiers;
- row images;
- record identifiers;
- provenance links;
- warnings;
- reconciliation results; and
- report metadata.

Canonical JSON may be used for reproducible interchange and reporting, while SQLite will store application case data and processed results.

### 4.5 Schema Mapping

MySQL row-based binlog output may refer to values using positional labels such as `@1`, `@2`, and `@3`. FactumDB uses schema metadata from `ibd2sdi` to map these positions to real column names.

```text
@1 → account_id
@2 → customer_name
@3 → balance
```

### 4.6 Table-Level Filtering

A binary log belongs to the entire MySQL server and may contain events from multiple databases and tables. When the examiner provides a specific `.ibd` file, FactumDB identifies the corresponding table and keeps only the relevant binary-log events for correlation.

### 4.7 Transaction Grouping

FactumDB groups individual row events into committed transactions using evidence such as:

- GTID;
- `BEGIN`;
- row events;
- XID;
- `COMMIT`;
- thread information;
- event order; and
- binary-log positions.

Instead of presenting isolated changes, the tool can show:

```text
Transaction TX-1452
- Update account 101
- Update account 205
- Insert transfer record 9001
- Commit
```

### 4.8 Record Identity Linking

FactumDB links events to logical records primarily using explicit primary or unique keys. These may be single-column keys or composite keys.

Where a key value changes, the tool may use before-images, after-images, transaction order, and schema mapping to preserve record identity. If a match is incomplete or ambiguous, the tool reports the uncertainty instead of silently guessing.

### 4.9 State Reconstruction

Once events are grouped and linked to records, FactumDB replays them chronologically to reconstruct the known history of each record.

The reconstruction is limited to what the available binary-log evidence supports. Missing logs, partial row images, schema changes, and unsupported data types are explicitly reported.

### 4.10 Reconciliation

FactumDB compares the final log-derived state with the physical state extracted from the `.ibd` file.

Possible rule-based results may include:

- **Exact** — reconstructed and physical values agree;
- **Strong** — key and all available comparable fields agree, but some values are unavailable;
- **Partial** — only part of the record can be compared;
- **Conflicting** — the available evidence disagrees;
- **Unresolved** — evidence is insufficient for a reliable conclusion; and
- **Unsupported** — the input or data type is outside the validated scope.

### 4.11 Evidence-Gap Detection

The tool explicitly identifies limitations such as:

- missing, purged, or expired binary-log files;
- disabled binary logging;
- corrupted InnoDB pages;
- incomplete row images;
- unsupported data types;
- schema drift;
- unmapped columns;
- inconsistent snapshot timing;
- missing keys; and
- ambiguous matches.

The tool must never present an incomplete timeline as complete.

### 4.12 Visualization and Reporting

The investigator-facing interface will provide:

- chronological record histories;
- grouped transaction timelines;
- physical-versus-log reconciliation views;
- evidence-gap warnings;
- conflict indicators;
- provenance details; and
- filtering by table, transaction, record, event type, or time range.

FactumDB will produce reproducible reports in JSON, CSV, HTML, or PDF containing case details, evidence hashes, tool versions, timelines, findings, limitations, and provenance.

---

## 5. Forensic Soundness

### Integrity

Original evidence is preserved and never silently modified. SHA-256 hashes are calculated during intake and verified against working copies.

### Repeatability

The tool records enough processing information for the same analysis to be repeated with the same evidence, utility versions, commands, configuration, and correlation rules.

### Provenance

Each finding is linked to its supporting source file, evidence hash, table, record key, binary-log file, event position, transaction identifier, raw utility output, and correlation rule.

### Transparent Limitations

The system does not fabricate missing row values, unavailable timestamps, transaction boundaries, deleted physical remnants, user attribution, or intent.

---

## 6. Technology Architecture

### Desktop Framework

- **Tauri** for a native Linux desktop application.

### Frontend

- **React** for record histories, transaction timelines, reconciliation views, warnings, and report controls.
- **Tailwind CSS** for UI styling.

### State Management

- **Zustand** for active case state, parsed evidence, selected records, filters, and current findings.

### Backend Sidecar

- **Python** to orchestrate the forensic utilities, parse and normalize outputs, perform correlation, reconstruct states, and prepare report data.

### Application Database

- **SQLite** to store case metadata, evidence registrations, normalized records, transaction groups, correlation results, provenance links, warnings, and report-generation state.
- Original evidence files remain outside SQLite and are handled through verified working copies.

### External Utilities

- `ibd2sdi`
- `innochecksum`
- `ibd2sql`
- `mysqlbinlog`

---

## 7. Initial Scope

The initial version will support:

- one selected MySQL 8.4.x release;
- the InnoDB storage engine;
- file-per-table `.ibd` files;
- row-based binary logs;
- offline analysis;
- unencrypted evidence;
- full row images where available;
- tables with explicitly defined primary keys;
- single-column and composite primary keys; and
- a validated subset of common MySQL data types.

This restriction supports forensic reliability and keeps the project achievable within one semester.

---

## 8. Initial Exclusions

The first version will not support:

- live acquisition or live-server modification;
- encryption bypass;
- redo- or undo-log parsing;
- statement-based log reconstruction;
- every MySQL version;
- complete schema-evolution handling;
- guaranteed deleted-row recovery;
- exact reconstruction of original SQL statements;
- automatic attribution to a person;
- determination of intent or responsibility; or
- legal conclusions.

---

# 9. Complete Workflow Story

## 9.1 Investigation Scenario

A financial company suspects that account balances were changed before a transfer was recorded. The investigator acquires:

```text
finance/accounts.ibd
finance/transfers.ibd
binlog.000018
binlog.000019
binlog.000020
```

The relevant schemas are:

```sql
CREATE TABLE accounts (
    account_id INT PRIMARY KEY,
    customer_name VARCHAR(100),
    balance DECIMAL(12,2)
);

CREATE TABLE transfers (
    transfer_id INT PRIMARY KEY,
    source_account INT,
    destination_account INT,
    amount DECIMAL(12,2),
    status VARCHAR(20)
);
```

The physical records extracted from the `.ibd` files show:

### `accounts.ibd`

| account_id | customer_name | balance |
|---:|---|---:|
| 101 | A. Perera | 4000.00 |
| 205 | B. Silva | 8500.00 |

### `transfers.ibd`

| transfer_id | source_account | destination_account | amount | status |
|---:|---:|---:|---:|---|
| 9001 | 101 | 205 | 1000.00 | COMPLETED |

The investigator wants to know how the balances reached these values, whether the changes occurred in one transaction, whether transfer 9001 belongs to that transaction, and whether the binary-log history agrees with the physical state.

## 9.2 Case Creation

The examiner creates:

```text
Case ID: FDB-2026-014
Case Name: Finance Balance Investigation
Examiner: Analyst 01
```

FactumDB creates a case workspace and SQLite case database.

## 9.3 Evidence Import and Hashing

The examiner imports the two `.ibd` files and three binary logs. FactumDB classifies each file, calculates its SHA-256 hash, creates a working copy, hashes the copy, and verifies that the hashes match.

All later processing uses the verified working copies.

## 9.4 Page-Integrity Checking

FactumDB runs `innochecksum` on the `.ibd` working copies.

```text
accounts.ibd   → pages valid
transfers.ibd  → pages valid
```

The command, utility version, output, errors, and exit status are recorded.

## 9.5 Schema Extraction

FactumDB runs `ibd2sdi` and maps positional log fields:

### `finance.accounts`

```text
@1 → account_id
@2 → customer_name
@3 → balance
Primary key → account_id
```

### `finance.transfers`

```text
@1 → transfer_id
@2 → source_account
@3 → destination_account
@4 → amount
@5 → status
Primary key → transfer_id
```

## 9.6 Physical Row Extraction

FactumDB runs `ibd2sql`, normalizes the extracted rows, and stores the normalized case results and provenance references in SQLite.

## 9.7 Binary-Log Decoding and Filtering

FactumDB runs `mysqlbinlog`. The logs may include many tables, but FactumDB filters for:

```text
finance.accounts
finance.transfers
```

Assume the relevant sequence is:

```text
GTID: 4f8a:1452
BEGIN

UPDATE finance.accounts
Before: @1=101, @2="A. Perera", @3=5000.00
After:  @1=101, @2="A. Perera", @3=4000.00

UPDATE finance.accounts
Before: @1=205, @2="B. Silva", @3=7500.00
After:  @1=205, @2="B. Silva", @3=8500.00

INSERT finance.transfers
After: @1=9001, @2=101, @3=205, @4=1000.00, @5="COMPLETED"

XID: 8821
COMMIT
```

## 9.8 Schema Mapping

FactumDB converts the positional values into named fields.

```text
account_id 101: balance 5000.00 → 4000.00
account_id 205: balance 7500.00 → 8500.00
transfer_id 9001: inserted for 1000.00
```

## 9.9 Transaction Grouping

Using the GTID, `BEGIN`, event order, XID, and `COMMIT`, FactumDB groups all three events:

```text
Transaction TX-1452
1. Debit account 101 by 1000.00
2. Credit account 205 by 1000.00
3. Insert transfer 9001
4. Commit
```

## 9.10 Record Identity Linking

FactumDB links each event using the explicit primary key:

```text
account_id = 101 → physical account record 101
account_id = 205 → physical account record 205
transfer_id = 9001 → physical transfer record 9001
```

Because the keys are explicit and the row images are complete, the matches are unambiguous.

## 9.11 State Reconstruction

### Account 101

```text
Before TX-1452: balance = 5000.00
After TX-1452:  balance = 4000.00
```

### Account 205

```text
Before TX-1452: balance = 7500.00
After TX-1452:  balance = 8500.00
```

### Transfer 9001

```text
Before TX-1452: record absent
After TX-1452:  transfer record present and marked COMPLETED
```

## 9.12 Reconciliation

FactumDB compares the reconstructed final state with the physical rows.

```text
Account 101
Log-derived balance: 4000.00
Physical balance:    4000.00
Result: Exact

Account 205
Log-derived balance: 8500.00
Physical balance:    8500.00
Result: Exact

Transfer 9001
Log-derived record: present
Physical record:    present
Result: Exact
```

The evidence supports the transaction history, but FactumDB does not claim who performed it or why.

## 9.13 Missing-Log Variant

Suppose `binlog.000019` is missing.

```text
binlog.000018
binlog.000020
```

FactumDB reports:

```text
Coverage gap detected: binlog.000019 is unavailable.
Impact: The record timeline may be incomplete.
```

If the physical balance does not match the available reconstructed state, the tool reports an unresolved result rather than claiming definite tampering:

```text
Reconciliation result: Unresolved
Reason: A binary-log coverage gap exists between the available events and the physical snapshot.
```

## 9.14 Examiner Review

The examiner can select `TX-1452` and view:

- transaction identifier and GTID;
- commit status;
- source log file and positions;
- affected tables and record keys;
- before and after values;
- reconciliation results;
- warnings;
- raw-output references; and
- evidence hashes.

Each finding can be traced to its source evidence and processing artefacts.

## 9.15 Report Export

The examiner exports a PDF report containing:

1. Case details
2. Evidence inventory
3. SHA-256 hashes
4. Utility versions and commands
5. Page-integrity results
6. Schema mappings
7. Transaction timeline
8. Record histories
9. Reconciliation results
10. Evidence gaps and limitations
11. Provenance references
12. Examiner notes

The same case can also be exported as JSON or CSV for independent checking.

---

# 10. Value of FactumDB

FactumDB helps analysts move from separate low-level database artefacts to a traceable history of database activity.

It can support:

- digital forensic investigations;
- incident response;
- internal auditing and fraud review;
- database consistency verification;
- deletion-event analysis where supported by available evidence;
- evidence-gap detection; and
- examiner-reviewed reporting.

Its practical benefits include reducing manual correlation, showing transaction context, linking historical events to physical records, preserving provenance, and producing repeatable reports.

---

# 11. Key Project Contribution

The project is not simply:

```text
ibd2sql + mysqlbinlog + GUI
```

Its contribution is the integrated workflow:

```text
Raw Evidence
    ↓
Evidence Registration and Hashing
    ↓
Verified Working Copies
    ↓
Schema, Integrity, Row, and Log Extraction
    ↓
Normalization
    ↓
Table-Level Matching
    ↓
Schema Mapping
    ↓
Transaction Grouping
    ↓
Record Identity Linking
    ↓
Chronological State Reconstruction
    ↓
Physical-versus-Log Reconciliation
    ↓
Timeline, Provenance, and Report
```

This integrated, traceable, and examiner-oriented workflow is the central idea of FactumDB.
