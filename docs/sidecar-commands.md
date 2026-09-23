# Sidecar application commands

The sidecar accepts one JSON object per line on stdin and writes one correlated
JSON response per line on stdout. Protocol version remains 1. Application commands
delegate to existing use cases and the pipeline orchestrator.

## Configuration

```python
from sidecar.composition import build_application_services
from sidecar.main import main

services = build_application_services(
    dependencies, adapters, workspaces=workspaces, inspector=inspector,
)
main(services)
```

`dependencies` is the existing `PipelineDependencies` bundle; `adapters` is an
`ExtractionAdapters` bundle. All commands share those repositories, ID generator,
clock, hasher and working-copy manager. Production repositories and normalization
must be supplied by the bootstrap caller. Tests use in-memory implementations.
For an alternate transport or tests, use `build_router(services)` and `serve`.

Running `python -m sidecar.main` currently starts the unconfigured transport:
`health` works and reports `application_configured: false`. The eight application
commands return `ApplicationNotConfiguredError` for otherwise valid payloads.
No temporary database is silently created. Configuring concrete production
dependencies and connecting Tauri remain separate tasks.

## Command contracts

All listed fields are required nonempty strings. Unknown payload fields, missing
fields, nulls, booleans, numbers and collections are rejected with
`InvalidPayloadError` before a service is called. Names and identifiers are trimmed;
valid source paths are preserved exactly, including whitespace in filenames.

| Command | Payload fields | Result / behavior |
|---|---|---|
| `health` | None | Name, readiness, protocol, `application_configured` |
| `create_case` | `case_name`, `examiner` | Flat case object: `case_id`, `case_name`, `examiner`, `created_at`, `workspace_path` |
| `register_evidence` | `case_id`, `source_path` | Evidence metadata and initial verification status |
| `verify_evidence` | `case_id`, `evidence_id` | Working-copy metadata and verification result |
| `start_pipeline` | `case_id` | Creates a pending run; does not execute a stage |
| `run_next_stage` | `run_id` | Executes the next stage synchronously and returns the updated run |
| `get_pipeline_status` | `run_id` | Reads persisted state without executing or changing anything |
| `cancel_pipeline` | `run_id` | Records a cancellation request; applied at the next execution boundary |
| `retry_pipeline` | `run_id` | Resets a retryable failed stage to pending; does not execute it |

Evidence results contain `evidence_id`, `case_id`, `source_path`, `filename`, `kind`,
`size_bytes`, `source_sha256`, `registered_at`, `verification_status`,
`working_copy_path`, `working_copy_sha256`, `acquisition_method`, and `verified`.
Timestamps are ISO strings, enum values are strings, and absent working-copy
fields are null.

Pipeline results contain `run_id`, `case_id`, `created_at`, `cancel_requested`,
`complete`, `stopped`, and `stages`. Each stage has `stage`, `status`, and `attempts`.
Attempts include number, status, start/end timestamps, item count, error code,
error message and skip reason. This retains failure history and applicability
reasons at the frontend boundary.

## Request and response examples

```json
{"request_id":"req-1","command":"start_pipeline","payload":{"case_id":"case-1"}}
```

The response envelope always contains `request_id`, `ok`, `result`, `error_code`
and `error_message`. Successful commands set the error fields to null; failed
commands set result to null. Unknown cases or run IDs, for example, produce:

```json
{"request_id":"req-1","ok":false,"result":null,"error_code":"NotFoundError","error_message":"case not found: case-1"}
```

Application errors retain their class names (`NotFoundError`, `ConflictError`,
`PrerequisiteError`, `EvidenceIntegrityError`). Malformed request envelopes use
`invalid_request`; unknown commands use `unknown_command`. Payload validation
errors preserve the supplied request ID. A failed command does not stop later
requests from being served.

`ok: true` means the command returned normally, not that forensic processing
succeeded. The orchestrator records tool failures inside the returned run. After
`run_next_stage`, inspect stage statuses and attempt errors. A `SKIPPED` stage
includes its reason and is not an error.

## Execution and limitations

The frontend should start the run, then request one stage at a time until the
returned `stopped` flag is true. Between stages it can request cancellation. Send
another `run_next_stage` to apply that request and mark pending stages cancelled.
The transport processes requests sequentially; it cannot answer status or cancel
commands while a synchronous stage is executing. No background worker, process
termination, or asynchronous progress stream is introduced here.

Retry applies only to a recorded failed stage whose handler declares it retryable.
It is not crash recovery: an attempt left `RUNNING` by a process crash is not
converted to failed by these commands. Retry idempotency and persistent recovery
remain separate work. Existing progress publishers still receive pipeline events;
they must not write unframed output to the command-response stdout stream.

The JSON-lines tests exercise all eight commands through real application use
cases, composed pipeline handlers and domain services with controlled dependencies.
They cover validation, result serialization, failures, cancellation between stages,
retry, missing identifiers and unconfigured service behavior.
