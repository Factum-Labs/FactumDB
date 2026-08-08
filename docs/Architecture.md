# FactumDB Architecture and End-to-End Workflow

## 1. Finalized Architecture

FactumDB uses:

- **Architectural style:** Layered Modular Monolith
- **Architectural pattern:** Hexagonal Architecture (Ports and Adapters)
- **Workflow style:** Pipe-and-Filter processing pipeline

The central rule is:

> The application layer decides **when and in what order** work is performed, the domain layer decides **how forensic evidence is interpreted**, and adapters perform technology-specific operations.

## 2. Architecture Diagram

<!-- ![FactumDB architecture](./factumdb_architecture.png) -->

```text
React / Tauri UI
        |
    Input Adapter
        |
+--------------------------------------+
|          Application Core            |
|                                      |
|  Application Layer                   |
|  +--------------------------------+  |
|  | Pipeline Orchestrator          |  |
|  | - controls processing order    |  |
|  | - checks prerequisites         |  |
|  | - handles failures             |  |
|  | - invokes ports and services   |  |
|  +--------------------------------+  |
|                 |                    |
|                 v                    |
|  Domain Layer                        |
|  +--------------------------------+  |
|  | TransactionGroupingService     |  |
|  | RecordCorrelationService       |  |
|  | StateReconstructionService     |  |
|  | ReconciliationService          |  |
|  +--------------------------------+  |
+--------------------------------------+
        |
    Output Ports
        |
        +-- Innochecksum Adapter
        +-- Ibd2Sdi Adapter
        +-- Ibd2Sql Adapter
        +-- MysqlBinlog Adapter
        +-- SQLite Adapter
        +-- Filesystem Adapter
        +-- Report Adapter
```

---

## 3. Component Responsibilities

### 3.1 React / Tauri UI

The UI is the investigator-facing presentation layer.

It is responsible for:

- creating and opening cases;
- importing `.ibd` files and binary logs;
- displaying hash-verification results;
- starting complete or partial analysis;
- displaying extraction and correlation progress;
- presenting transaction timelines and record histories;
- showing reconciliation results, evidence gaps, and provenance; and
- exporting reports.

The UI must not perform forensic matching, reconstruction, reconciliation, or direct database access.

### 3.2 Input Adapter

The input adapter translates frontend actions into application use-case requests.

Typical responsibilities:

- receive Tauri commands;
- validate request fields;
- convert frontend data into backend request objects;
- invoke the correct use case;
- convert responses into UI-friendly data; and
- forward progress and warning events to React.

Example:

```text
User clicks "Run Complete Analysis"
        |
React sends a Tauri command
        |
Input adapter validates the case ID
        |
RunCompleteAnalysisUseCase is invoked
```

### 3.3 Application Layer

The application layer coordinates user operations. It contains use cases such as:

- `CreateCase`
- `RegisterEvidence`
- `VerifyEvidence`
- `RunPageValidation`
- `ExtractSchema`
- `ExtractPhysicalRows`
- `DecodeBinaryLogs`
- `NormalizeEvidence`
- `RunCorrelation`
- `RunReconciliation`
- `GenerateReport`
- `RunCompleteAnalysis`

It controls the workflow, but it does not contain the detailed forensic algorithms.

### 3.4 Pipeline Orchestrator

The pipeline orchestrator is the central coordinator.

It:

- controls execution order;
- checks prerequisites;
- invokes external capabilities through ports;
- invokes domain services at the correct stages;
- stores intermediate results;
- tracks pipeline status;
- reports progress;
- records failures and warnings; and
- prevents invalid stage execution.

Processing order:

```text
Evidence Registration
        |
SHA-256 Hashing
        |
Verified Working-Copy Creation
        |
InnoDB Page Validation
        |
Schema Extraction
        |
Physical-Row Extraction
        |
Binary-Log Decoding
        |
Normalization
        |
Transaction Grouping
        |
Record Correlation
        |
State Reconstruction
        |
Physical-versus-Log Reconciliation
        |
Result Persistence
        |
Report Generation
```

### 3.5 Domain Layer

The domain layer contains FactumDB's original forensic analysis logic. It receives normalized objects, not raw command-line text.

#### TransactionGroupingService

Groups binlog events into committed, rolled-back, incomplete, or unresolved transactions using:

- GTID;
- `BEGIN`;
- row events;
- XID;
- `COMMIT` or rollback markers;
- thread/session information; and
- log positions.

#### RecordCorrelationService

Links binlog events to logical records using:

- database and table identity;
- primary or composite keys;
- before and after row images;
- schema mappings; and
- available physical-record values.

Ambiguous matches are reported rather than guessed.

#### StateReconstructionService

Replays correlated events chronologically to reconstruct record histories. It never invents missing values.

#### ReconciliationService

Compares the reconstructed final state with the physical `.ibd` state and returns a rule-based result such as:

- Exact;
- Strong;
- Partial;
- Conflicting;
- Unresolved; or
- Unsupported.

---

## 4. Output Ports and Adapters

An output port is an interface defined by the application core. An adapter implements that interface with a specific technology.

### 4.1 Innochecksum Adapter

Implements a page-validation port and:

- executes `innochecksum` on verified working copies;
- captures command, version, output, error, and exit status;
- identifies valid, damaged, or unreadable pages; and
- returns a normalized integrity result.

### 4.2 Ibd2Sdi Adapter

Implements a schema-extraction port and extracts:

- database and table names;
- column names and positions;
- data types;
- primary or composite keys; and
- index metadata.

Example:

```text
@1 -> account_id
@2 -> customer_name
@3 -> balance
Primary key -> account_id
```

### 4.3 Ibd2Sql Adapter

Implements a row-extraction port and:

- executes `ibd2sql` on verified `.ibd` copies;
- preserves raw output;
- parses supported rows; and
- returns normalized physical records.

### 4.4 MysqlBinlog Adapter

Implements a binlog-decoding port and extracts:

- database and table name;
- event type;
- before and after row images;
- timestamp;
- GTID;
- XID;
- transaction markers; and
- source filename and positions.

### 4.5 SQLite Adapter

Implements repository ports and stores:

- cases;
- evidence registrations and hashes;
- processing states;
- normalized schemas and records;
- decoded events;
- grouped transactions;
- correlations;
- histories;
- reconciliation results;
- warnings;
- provenance; and
- report metadata.

Original evidence remains in the controlled case workspace.

### 4.6 Filesystem Adapter

Handles:

- evidence access;
- SHA-256 hashing;
- controlled working-copy creation;
- hash verification;
- raw-output preservation; and
- case-directory management.

### 4.7 Report Adapter

Generates PDF, HTML, JSON, or CSV reports from structured case data.

---

# 5. Complete End-to-End Example

## 5.1 Scenario

A financial company suspects that account balances were changed before a transfer record was created.

The investigator acquires:

```text
finance/accounts.ibd
finance/transfers.ibd
binlog.000018
binlog.000019
binlog.000020
```

Schemas:

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

Physical `.ibd` records:

### accounts

| account_id | customer_name | balance |
| ---------: | ------------- | ------: |
|        101 | A. Perera     | 4000.00 |
|        205 | B. Silva      | 8500.00 |

### transfers

| transfer_id | source_account | destination_account |  amount | status    |
| ----------: | -------------: | ------------------: | ------: | --------- |
|        9001 |            101 |                 205 | 1000.00 | COMPLETED |

The investigator wants to determine:

- how account 101 reached 4000.00;
- how account 205 reached 8500.00;
- whether the changes occurred in one transaction;
- whether transfer 9001 belongs to that transaction;
- whether the log history agrees with the physical tables; and
- whether evidence gaps limit the conclusion.

## 5.2 Case Creation

The investigator creates:

```text
Case ID: FDB-2026-014
Case Name: Finance Balance Investigation
Examiner: Analyst 01
```

Flow:

```text
React UI
    |
Input Adapter
    |
CreateCaseUseCase
    |
CaseRepositoryPort
    |
SQLite Adapter
```

## 5.3 Evidence Registration and Hashing

The files are imported. The orchestrator invokes filesystem and hashing ports.

Example:

```text
accounts.ibd
SHA-256: 9c7f...e214

transfers.ibd
SHA-256: 51ab...a82c

binlog.000020
SHA-256: 81f4...35da
```

The hashes and metadata are stored through the SQLite adapter.

## 5.4 Verified Working Copies

The filesystem adapter:

1. creates a controlled copy of each evidence file;
2. hashes each copy;
3. compares the hashes; and
4. returns a verification result.

```text
Original hash: 9c7f...e214
Copy hash:     9c7f...e214
Status: Verified
```

All extraction runs against verified copies.

## 5.5 Page Validation

The orchestrator invokes the page-validation port.

```text
accounts.ibd
Pages checked: 126
Damaged pages: 0
Status: Valid
```

The exact command, version, output, error, and status are recorded.

## 5.6 Schema Extraction

The Ibd2Sdi adapter returns:

```text
finance.accounts
@1 -> account_id
@2 -> customer_name
@3 -> balance
Primary key -> account_id

finance.transfers
@1 -> transfer_id
@2 -> source_account
@3 -> destination_account
@4 -> amount
@5 -> status
Primary key -> transfer_id
```

## 5.7 Physical-Row Extraction

The Ibd2Sql adapter returns normalized records:

```text
finance.accounts
- account_id = 101, balance = 4000.00
- account_id = 205, balance = 8500.00

finance.transfers
- transfer_id = 9001
- source_account = 101
- destination_account = 205
- amount = 1000.00
- status = COMPLETED
```

## 5.8 Binary-Log Decoding

The MysqlBinlog adapter decodes all available logs and filters relevant events.

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

## 5.9 Normalization

The application converts all tool outputs into canonical objects such as:

```text
Schema
PhysicalRecord
BinlogEvent
TransactionMarker
ProvenanceReference
Warning
```

## 5.10 Transaction Grouping

The orchestrator invokes `TransactionGroupingService`.

```text
Transaction: TX-1452
GTID: 4f8a:1452
XID: 8821
Status: Committed

Events:
1. Update account 101
2. Update account 205
3. Insert transfer 9001
```

## 5.11 Record Correlation

The orchestrator invokes `RecordCorrelationService`.

```text
account_id = 101 -> physical account record 101
account_id = 205 -> physical account record 205
transfer_id = 9001 -> physical transfer record 9001
```

Method:

```text
Primary-key exact match
```

## 5.12 State Reconstruction

The orchestrator invokes `StateReconstructionService`.

```text
Account 101
Before TX-1452: balance = 5000.00
After TX-1452:  balance = 4000.00

Account 205
Before TX-1452: balance = 7500.00
After TX-1452:  balance = 8500.00

Transfer 9001
Before TX-1452: record absent
After TX-1452:  record inserted, amount = 1000.00
```

## 5.13 Reconciliation

The orchestrator invokes `ReconciliationService`.

```text
Account 101
Log-derived balance: 4000.00
Physical balance:    4000.00
Classification: Exact

Account 205
Log-derived balance: 8500.00
Physical balance:    8500.00
Classification: Exact

Transfer 9001
Log-derived record: Present
Physical record:    Present
Classification: Exact
```

FactumDB may state that the available database evidence consistently supports the reconstructed transaction. It cannot identify who performed it or determine intent.

## 5.14 Missing-Log Variant

Assume `binlog.000019` is missing.

```text
Coverage gap detected:
binlog.000019 is unavailable.

Impact:
The transaction timeline may be incomplete.
```

Suppose the available logs reconstruct account 101 to 4500.00, while the `.ibd` file contains 4000.00.

```text
Classification: Unresolved

Reason:
The states differ, but the missing binary log may contain the unavailable change.
```

FactumDB does not falsely classify this as tampering.

## 5.15 UI Presentation

The UI may display:

```text
Evidence files:       5
Verified files:       5
Tables parsed:        2
Transactions grouped: 1
Records correlated:   3
Exact matches:        3
Coverage gaps:        0
```

The examiner can open `TX-1452` and inspect:

- GTID and XID;
- source file and positions;
- affected records;
- before and after values;
- matching rule;
- reconciliation classification; and
- provenance.

## 5.16 Report Generation

The examiner selects **Export PDF Report**.

```text
React UI
    |
Input Adapter
    |
GenerateReportUseCase
    |
ReportGeneratorPort
    |
PDF Report Adapter
```

The report includes:

1. case details;
2. evidence inventory;
3. SHA-256 hashes;
4. tool versions and commands;
5. page-integrity results;
6. schema mappings;
7. transaction timeline;
8. record histories;
9. reconciliation results;
10. evidence gaps;
11. provenance;
12. limitations; and
13. examiner notes.

---

## 6. Dependency Rules

1. The UI depends on the input adapter, not directly on SQLite or domain services.
2. The application layer invokes ports and domain services.
3. The domain layer does not depend on React, Tauri, SQLite, filesystem paths, or command-line utilities.
4. Adapters translate between external technologies and FactumDB's canonical model.
5. The pipeline orchestrator controls stage order; domain services perform the analysis.

---

## 7. Suggested Backend Module Layout

```text
factumdb/
|
+-- application/
|   +-- use_cases/
|   +-- orchestration/
|   +-- ports/
|
+-- domain/
|   +-- models/
|   +-- services/
|
+-- infrastructure/
|   +-- adapters/
|
+-- interfaces/
    +-- tauri_commands.py
    +-- request_models.py
    +-- response_models.py
```

---

## 8. Final Architecture Statement

> FactumDB is implemented as a Layered Modular Monolith using Hexagonal Architecture. The React/Tauri UI communicates with the application core through an input adapter. The application layer contains the central pipeline orchestrator, which controls evidence registration, integrity verification, extraction, normalization, domain analysis, persistence, and reporting. The separate domain layer performs transaction grouping, record correlation, state reconstruction, and reconciliation using normalized forensic data. External tools, SQLite, filesystem services, hashing, and report generation are accessed through output ports and technology-specific adapters. This structure supports forensic repeatability, testability, maintainability, and achievable implementation within one semester.
