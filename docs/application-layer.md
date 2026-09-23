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
