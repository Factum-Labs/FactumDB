# FactumDB Application Layer

The application layer turns UI and pipeline requests into coordinated operations. It owns
workflow, prerequisites, and persistence calls; forensic interpretation remains in
`backend/core/domain`, and technology-specific work remains behind ports.

## Implemented use cases

| Area | Use case | Collaborating ports |
|---|---|---|
| Case | `CreateCaseUseCase` | `CaseRepository`, `CaseWorkspace`, `IdGenerator`, `Clock` |
| Intake | `RegisterEvidenceUseCase` | `CaseRepository`, `EvidenceRepository`, `EvidenceInspector`, `FileHasher` |
| Integrity | `VerifyEvidenceUseCase` | `CaseRepository`, `EvidenceRepository`, `WorkingCopyManager`, `FileHasher` |
| Audit | `ToolRunAuditService` | `ToolRunRepository`, `RawOutputStore`, `FileHasher` |
| Extraction | `RunPageValidationUseCase` | `PageValidator`, `ExtractionRepository` |
| Extraction | `ExtractSchemaUseCase` | `SchemaExtractor`, `ExtractionRepository` |
| Extraction | `ExtractPhysicalRowsUseCase` | `PhysicalRowExtractor`, `ExtractionRepository` |
| Extraction | `DecodeBinaryLogsUseCase` | `BinlogDecoder`, `ExtractionRepository` |
| Normalization | `NormalizeEvidenceUseCase` | `EvidenceNormalizer`, `ExtractionRepository` |
| Analysis | `GroupTransactionsUseCase` | `DomainRepository`, `TransactionGroupingService` |
| Analysis | `CorrelateRecordsUseCase` | `DomainRepository`, `RecordCorrelationService` |
| Analysis | `ReconstructStateUseCase` | `DomainRepository`, `StateReconstructionService` |
| Analysis | `ReconcileRecordsUseCase` | `DomainRepository`, `ReconciliationService` |

## Final wiring

```text
React action
    -> Tauri command / Python sidecar input adapter
    -> one application use case
    -> application ports
       -> filesystem, SQLite, or external-tool adapters
    -> existing domain service where forensic reasoning is required
    -> response returned through Tauri to React
```

The future pipeline orchestrator calls these use cases in stage order. It will own stage
status, safe retry, cancellation between stages, and progress publication; those concerns are
intentionally not duplicated inside the individual use cases.

## Integration rules

### Shared packages and model contracts

`core.application.ports` is a package; the former `ports.py` was removed. Its
`common`, `filesystem`, `extraction`, `analysis`, and `workflow_repositories`
modules hold the workflow contracts. The package re-exports those contracts and
the existing granular `*RepositoryPort` interfaces. Existing package-level imports
continue to work. Workflow protocols and granular storage interfaces still have
different method signatures; a SQLite implementation needs explicit wiring to meet
the workflow requirements, including case-scoped evidence access.

`core.application.models` is also a package. Requests and responses live in
`create_case_models`, `evidence_models`, `extraction_models`, and `audit_models`.
`Case` lives only in `core.domain.models.case`; `EvidenceFile`, `ToolRun`, their
status enums and `RawOutputReference` live only in `core.domain.models.evidence`.
The application package re-exports these exact domain types, not copies.

The consolidated domain models retain the application lifecycle: timezone-aware
datetime values, required case workspace, initially unverified evidence, immutable
verification transitions, executable hash, arguments, and separate stdout/stderr
references. Evidence also retains `acquisition_method`. Storage-facing names such
as `case_id`, `evidence_id`, `sha256_original`, and `tool_run_id` are read-only
properties over the same data. `command` is a display string, not a shell command
to execute; legacy raw-output properties refer to stdout.

Constructor migration: instantiate domain models using the workflow fields (`id`,
`name`, `source_path`, `kind`, etc.), and convert database timestamp strings to
aware datetimes in persistence adapters. `Case.create` now requires a workspace
path, case ID and timestamp supplied by the application, keeping the domain free
of UUID generation and wall-clock reads. `CreateCaseRequest` accepts `case_name`
and `examiner` (`name` is a read
alias); `CreateCaseResponse` takes one canonical `Case` and exposes the flat
case ID, name, examiner and ISO timestamp through properties. Dataclass serialization
uses the stored fields, so transport adapters must explicitly select their wire
format. No concrete SQLite implementation was changed by this consolidation.

- Tauri and the sidecar import application use cases, not domain services directly.
- SQLite implements the repository ports in `core.application.ports`.
- Utility adapters implement `PageValidator`, `SchemaExtractor`, `PhysicalRowExtractor`, and
  `BinlogDecoder`.
- Only evidence with a SHA-256-verified working copy may reach an extraction adapter.
- The `DomainRepository` assembles case-scoped implementations of the existing read-only
  domain ports and persists each immutable domain result.
- Expected workflow failures use the exceptions in `core.application.errors`; adapters should
  not convert evidence limitations into infrastructure exceptions.

## Implemented Nisal infrastructure

The filesystem package now provides concrete implementations for case workspaces, evidence
inspection, streamed SHA-256 hashing, atomic verified working-copy creation, and immutable raw
tool-output preservation. All paths are constrained beneath the configured workspace root, and
working copies are published without overwriting an existing file.

The application orchestration package provides the ordered analysis stage model, persistent
state transitions, attempt history, prerequisite enforcement, duplicate-run prevention,
progress events, failure capture, safe-retry policy, run-next/run-all operations, and
cancellation between stages. Persistence and progress delivery remain ports so SQLite and
Tauri can be connected by their owners.

The Python sidecar skeleton provides a versioned JSON-lines request/response boundary, command
routing, structured failures, request correlation, and a health command. Application commands
can be registered in its composition root after the SQLite repositories are supplied.

## Deferred work

This layer does not yet provide concrete SQLite, external-tool, or Tauri adapters. The sidecar
transport exists, but production application commands have not been registered yet.
Concrete stage handlers still need to assemble the evidence-specific use cases once those
adapters are available. Report generation is a separate increment.
