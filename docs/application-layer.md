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

The pipeline orchestrator calls configured handlers for these use cases in stage order. It owns stage
status, retry eligibility, cancellation between stages, and progress publication; those concerns are
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

Concrete SQLite and Tauri integration remain outstanding. The sidecar transport exists,
but production application commands have not been registered yet. The generic stage handlers
and extraction bridges exist; production composition still needs to assemble the use cases
with repositories and a case-scoped schema lookup. Report generation is a separate increment.

## External-tool extraction integration

`adapters.tools` exports the following implementations for injection into extraction use cases:

| Application port | Implementation | Behavior |
|---|---|---|
| `PageValidator` | `InnochecksumAdapter` | Already matches `validate(path)`; no wrapper needed |
| `SchemaExtractor` | `Ibd2SdiSchemaExtractor` | Wraps `extract_schema(path)` in a schema tuple |
| `PhysicalRowExtractor` | `Ibd2SqlPhysicalRowExtractor` | Converts rows to a tuple; optionally appends deleted rows |
| `BinlogDecoder` | `MysqlBinlogDecoder` | Binds schema lookup and returns events, markers and warnings |

Example composition (the evidence/results repositories, schema repository and clock are
supplied by the caller):

```python
from adapters.tools import (
    Ibd2SdiAdapter, Ibd2SdiSchemaExtractor,
    Ibd2SqlAdapter, Ibd2SqlPhysicalRowExtractor,
    InnochecksumAdapter, MysqlBinlogAdapter, MysqlBinlogDecoder,
)
from core.application.use_cases.extraction import (
    RunPageValidationUseCase, ExtractSchemaUseCase,
    ExtractPhysicalRowsUseCase, DecodeBinaryLogsUseCase,
)

validate = RunPageValidationUseCase(evidence, InnochecksumAdapter(), results, clock)
schema = ExtractSchemaUseCase(
    evidence, Ibd2SdiSchemaExtractor(Ibd2SdiAdapter()), results, clock,
)
rows = ExtractPhysicalRowsUseCase(
    evidence,
    Ibd2SqlPhysicalRowExtractor(Ibd2SqlAdapter("/tools/ibd2sql/main.py")),
    results, clock,
)
decode = DecodeBinaryLogsUseCase(
    evidence,
    MysqlBinlogDecoder(MysqlBinlogAdapter(), case_schemas.schema_for),
    results, clock,
)
```

The schema lookup must be bound to the same case as the use case invocation. Build a
separate decoder for each case; neither the decoder port nor the utility receives a case ID.
Populate schemas before decoding. A missing schema produces a retained `SCHEMA_NOT_FOUND`
warning, not invented column names. `DecodedBinlog.warnings` defaults to an empty tuple for
existing callers. `ExtractionRepository.save_decoded_binlog` must save warnings together
with events and markers, including when decoding yields no events. Warning counts are not
included in the operation receipt's event/marker count.

Row extraction defaults to live rows. Set `include_deleted=True` to also run the utility
with `--delete only` and retain `is_deleted` on those records. Failure of either invocation
propagates before the use case saves any row bundle. Other tool exceptions also propagate;
the existing innochecksum adapter's damaged/unknown classifications are preserved.

Use cases enforce evidence type and verified working-copy prerequisites. Wrappers do not
rehash evidence, implement normalization, or add raw-output/tool-run auditing to utility
invocations. Those remain separate integration work. Tool parsing implementations are
unchanged. Tests run the actual parsers with mocked subprocess results; real utility
execution against evidence on Linux remains to be validated. The backend wheel now includes
the `adapters` package so these implementations are included in installations.
