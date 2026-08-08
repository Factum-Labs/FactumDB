# FactumDB — 8-Week Work Plan and Work Distribution

## Project Constraints

- **Duration:** 8 weeks
- **Team size:** 3 members
- **Target:** Complete the main functional implementation by the end of Week 6
- **Weeks 7–8:** Evaluation, hardening, documentation, packaging, and demonstration

## 1. Team Responsibility Areas

| Member | Primary ownership | Approximate workload |
|---|---|---:|
| **Nisal** | Application architecture, pipeline orchestration, evidence integrity, filesystem handling | 33% |
| **Gimhan** | Utility adapters, normalization, SQLite persistence | 33% |
| **Yasiru** | Domain engine, React/Tauri UI, reporting and visualization | 33% |

Primary ownership does not mean that one member works alone. Every major component should be reviewed and tested by at least one other team member.

## 2. High-Level Work Distribution

### Nisal

- Finalize and maintain the software architecture.
- Implement the application layer and use cases.
- Implement the central pipeline orchestrator.
- Implement SHA-256 hashing and evidence registration.
- Implement verified working-copy creation.
- Manage filesystem and case workspace operations.
- Implement pipeline state management and failure handling.
- Integrate adapters and domain services.
- Verify forensic integrity and provenance.
- Lead system integration testing.

### Gimhan

- Implement adapters for `ibd2sdi`, `innochecksum`, `ibd2sql`, and `mysqlbinlog`.
- Parse and normalize external utility outputs.
- Implement positional-field-to-schema mapping.
- Implement database and table filtering.
- Design and implement the SQLite schema.
- Implement repositories and persistence.
- Preserve raw outputs and provenance references.
- Implement JSON and CSV export data.
- Optimize database operations.

### Yasiru

- Implement the React/Tauri user interface.
- Implement Zustand state management.
- Implement transaction grouping.
- Implement record correlation.
- Implement state reconstruction.
- Implement physical-versus-log reconciliation.
- Create transaction timelines and record-history views.
- Create reconciliation and evidence-gap views.
- Implement report presentation and export interface.
- Test domain accuracy and UI behavior.

## 3. Weekly Work Plan

### Week 1 — Architecture, Scope, and Environment Setup

**Whole team**

- Freeze the initial project scope.
- Confirm the selected MySQL 8.4.x release.
- Configure the Linux development environment.
- Set up the Git repository, branches, issue tracking, and code review.
- Set up a controlled MySQL test instance.
- Generate a small test dataset containing inserts, updates, and deletes.
- Verify that all four external utilities work.
- Agree on canonical models and module interfaces.

**Nisal**

- Finalize the Layered Modular Monolith architecture.
- Finalize Hexagonal Architecture ports and adapters.
- Define application-layer use cases.
- Design the pipeline orchestrator and stage contracts.
- Design the case workspace and working-copy structure.
- Create the Python sidecar application skeleton.

**Gimhan**

- Install and test all four external utilities.
- Collect representative raw outputs.
- Draft the canonical JSON model.
- Draft the SQLite schema.
- Define repository interfaces.

**Yasiru**

- Initialize Tauri, React, Tailwind CSS, and Zustand.
- Build the basic application shell and navigation.
- Create a dummy dashboard.
- Define preliminary domain entities and service interfaces.

**Deliverable:** A project skeleton where the React/Tauri frontend can invoke a dummy Python sidecar operation.

### Week 2 — Case Management and Evidence Intake

**Nisal**

- Implement case creation and evidence registration.
- Implement SHA-256 hashing.
- Implement verified working-copy creation and verification.
- Implement evidence workspace organization.
- Implement initial pipeline stages and processing-state tracking.

**Gimhan**

- Implement `InnochecksumAdapter`.
- Implement `Ibd2SdiAdapter`.
- Capture commands, versions, executable details, exit codes, stdout, and stderr.
- Begin SQLite case and evidence repositories.

**Yasiru**

- Implement case-creation and evidence-import UI.
- Build the evidence inventory.
- Display filename, type, hash, status, and warnings.
- Connect the frontend to initial Tauri commands.

**Deliverable:** An investigator can create a case, import evidence, calculate hashes, create verified working copies, validate pages, and extract schema information.

### Week 3 — Row Extraction and Binary-Log Decoding

**Nisal**

- Extend the pipeline orchestrator.
- Add stage prerequisite checks and status tracking.
- Implement raw-output preservation and audit records.
- Implement pipeline progress events and utility-failure handling.

**Gimhan**

- Implement `Ibd2SqlAdapter`.
- Implement `MysqlBinlogAdapter`.
- Parse physical rows, row events, before/after images, GTIDs, XIDs, log positions, and transaction markers.
- Store normalized intermediate data in SQLite.

**Yasiru**

- Build extraction-status and progress screens.
- Build schema, table, physical-record, and decoded-event views.
- Display adapter errors and unsupported conditions.
- Compare parsed results with raw utility output.

**Deliverable:** FactumDB can extract and display schemas, physical rows, and decoded binary-log events.

### Week 4 — Normalization and Transaction Grouping

**Nisal**

- Complete orchestration from intake through normalization.
- Implement safe retry and cancellation where practical.
- Record stage inputs, outputs, warnings, and errors.
- Integrate persistence ports.
- Review evidence-handling and chain-of-custody behavior.

**Gimhan**

- Complete the canonical normalization model.
- Implement positional-field mapping such as `@1 → first schema column`.
- Implement database and table filtering.
- Complete repositories for schemas, physical records, binlog events, utility executions, and processing results.
- Create normalized test fixtures.

**Yasiru**

- Implement `TransactionGroupingService`.
- Group events using GTID, `BEGIN`, XID, `COMMIT`, rollback markers, event order, positions, and session information.
- Build the first transaction timeline.
- Test committed, rolled-back, incomplete, and interleaved transactions.

**Deliverable:** Normalized events can be filtered by table, grouped into transactions, stored, and displayed.

### Week 5 — Record Correlation and State Reconstruction

**Nisal**

- Integrate domain services into the pipeline.
- Implement processing-state validation.
- Coordinate data loading before domain stages.
- Handle partial, ambiguous, and unsupported results.
- Implement end-to-end integration tests.
- Ensure provenance is retained from extraction to findings.

**Gimhan**

- Prepare fixtures for single and composite primary keys, key changes, inserts, updates, deletes, partial row images, and unsupported values.
- Improve normalization based on domain requirements.
- Implement efficient provenance queries.

**Yasiru**

- Implement `RecordCorrelationService`.
- Implement primary-key and composite-key matching.
- Track identity across before and after row images.
- Implement `StateReconstructionService`.
- Build record-history and before/after comparison views.
- Return ambiguous results explicitly instead of guessing.

**Deliverable:** FactumDB can link binary-log events to physical records and reconstruct chronological record histories.

### Week 6 — Reconciliation, Reporting, and Feature Freeze

**Nisal**

- Integrate reconciliation into the pipeline.
- Implement missing-binlog-sequence detection.
- Finalize warning and failure policies.
- Integrate report generation as the final stage.
- Verify repeatability and audit completeness.
- Test the complete evidence-to-report workflow.

**Gimhan**

- Implement repositories for transactions, correlations, histories, reconciliation results, warnings, and report metadata.
- Implement JSON and CSV export.
- Add appropriate SQLite indexes.
- Verify that every finding links to supporting evidence.

**Yasiru**

- Implement `ReconciliationService`.
- Implement Exact, Strong, Partial, Conflicting, Unresolved, and Unsupported classifications.
- Build reconciliation and evidence-gap views.
- Implement PDF or HTML report presentation.
- Complete the dashboard and report-export interface.

**Deliverable:** A complete functional version supporting evidence intake, hashing, extraction, normalization, transaction grouping, correlation, reconstruction, reconciliation, visualization, and report export.

> **Feature freeze should occur at the end of Week 6.**

### Week 7 — Testing, Evaluation, and Hardening

**Nisal owns**

- Missing binary logs.
- Corrupted InnoDB pages.
- Invalid evidence files.
- Interrupted pipeline stages.
- Hash mismatch and working-copy failure.
- Repeatability and audit-trail completeness.
- Orchestration and integration defect fixing.

**Gimhan owns**

- Single-row inserts, updates, and deletes.
- Composite-key tables and primary-key changes.
- Positional-field mapping.
- Supported and unsupported data types.
- SQLite persistence correctness.
- Parsing and normalization defect fixing.

**Yasiru owns**

- Multi-table and rolled-back transactions.
- Concurrent/interleaved sessions.
- Transaction-boundary accuracy.
- Record-correlation and reconstruction accuracy.
- Reconciliation classifications.
- UI failure states and report correctness.

**Whole-team metrics**

- Transaction-boundary accuracy.
- Record-correlation accuracy.
- Reconciliation accuracy.
- False-positive and false-negative rates.
- Provenance accuracy.
- Repeatability.
- Processing time.
- Memory usage.

**Deliverable:** A tested release candidate with documented evaluation results, defects, and limitations.

### Week 8 — Documentation, Packaging, and Demonstration

**Nisal**

- Finalize architecture and pipeline documentation.
- Document forensic integrity and working-copy handling.
- Prepare build and installation instructions.
- Prepare the main live-demonstration workflow.
- Verify deployment on a clean Linux environment.

**Gimhan**

- Document utility adapters, normalization, SQLite, and provenance storage.
- Package synthetic datasets and expected results.
- Prepare evaluation tables and adapter limitations.

**Yasiru**

- Finalize UI polishing.
- Prepare the user guide with screenshots.
- Document the domain engine.
- Finalize report templates.
- Prepare presentation diagrams and demonstration visuals.
- Prepare a backup recorded demonstration.

**Whole team**

- Fix only critical and high-priority defects.
- Run the full workflow on a clean Linux environment.
- Verify evidence hashes, timelines, histories, findings, and reports.
- Rehearse the presentation.
- Tag and package the final release.

**Deliverable:** Working Linux application, source code, test datasets, evaluation results, README, installation guide, user guide, final report, presentation, and demonstration.

## 4. Subsystem Ownership Matrix

| Subsystem | Lead | Reviewer / support |
|---|---|---|
| Architecture and pipeline orchestrator | **Nisal** | Gimhan |
| Evidence intake and case workflow | **Nisal** | Yasiru |
| SHA-256 and working copies | **Nisal** | Gimhan |
| Pipeline integration and failure handling | **Nisal** | Yasiru |
| External utility adapters | **Gimhan** | Nisal |
| Canonical normalization | **Gimhan** | Yasiru |
| SQLite persistence | **Gimhan** | Nisal |
| Transaction grouping | **Yasiru** | Gimhan |
| Record correlation | **Yasiru** | Nisal |
| State reconstruction | **Yasiru** | Gimhan |
| Reconciliation | **Yasiru** | Gimhan |
| React/Tauri frontend | **Yasiru** | Nisal |
| Report presentation | **Yasiru** | Gimhan |
| Integration testing | **Nisal** | Both |
| Synthetic datasets and evaluation | **All members** | Cross-reviewed |
| Documentation | **All members by subsystem** | Cross-reviewed |

## 5. Recommended Team Process

### Weekly Sprint Structure

At the start of each week:

1. Select tasks from the weekly plan.
2. Assign clear acceptance criteria.
3. Confirm interfaces between members.
4. Identify integration dependencies.

At the end of each week:

1. Demonstrate completed functionality.
2. Review open defects.
3. Merge reviewed pull requests.
4. Update the risk list.
5. Adjust the following week's workload where necessary.

### Definition of Done

A task is complete only when:

- implementation is finished;
- tests pass;
- errors are handled;
- relevant logs or provenance are recorded;
- code is reviewed;
- documentation is updated;
- the feature is integrated into the main workflow.

## 6. Minimum Viable Product Priority

If the schedule becomes tight, prioritize:

1. Case creation and evidence registration
2. SHA-256 hashing and verified working copies
3. External utility orchestration
4. Canonical normalization
5. Transaction grouping
6. Primary-key-based record correlation
7. State reconstruction
8. Physical-versus-log reconciliation
9. Basic timelines and record-history views
10. Reproducible report export

Defer if necessary:

- runtime plugin discovery;
- advanced confidence scoring;
- broad support for complex MySQL data types;
- elaborate UI animations;
- extensive customization;
- optional export formats;
- nonessential performance optimization.
