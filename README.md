# FactumDB

FactumDB is a digital forensics project for reconstructing and reconciling MySQL/InnoDB evidence. It is designed as a **Layered Modular Monolith** using **Hexagonal Architecture**, with a **Pipe-and-Filter** style processing workflow.

The main goal of this README is to help team members understand how the project folders connect to the system architecture described in [docs/Architecture.md](docs/Architecture.md).

## Architecture Overview

FactumDB separates user interaction, workflow coordination, forensic domain logic, and technology-specific integrations into clear layers.

![FactumDB high-level architecture](images/High%20level%202.png)

At a high level:

- The frontend presents the application to the investigator.
- Tauri bridges frontend actions into backend requests.
- The application layer coordinates use cases and pipeline execution.
- The domain layer performs forensic reasoning.
- The adapters layer handles external tools, storage, files, and reports.

The central architecture rule is:

> The application layer decides when and in what order work is performed, the domain layer decides how forensic evidence is interpreted, and adapters perform technology-specific operations.

## Project Folder Structure

```text
FactumDB/
├── frontend/
├── src-tauri/
├── backend/
|   ├── core/
|   |   ├── application/
|   |   └── domain/
|   └── adapters/
├── docs/
├── images/
└── README.md
```

## How Folders Align With the Architecture

### `frontend/` - Presentation Layer

The `frontend/` folder contains the investigator-facing user interface.

This layer is responsible for:

- creating and opening cases;
- importing evidence files such as `.ibd` files and binary logs;
- displaying verification, extraction, and analysis progress;
- presenting transaction timelines, record histories, reconciliation results, and evidence gaps; and
- allowing report export actions.

The frontend should not contain forensic algorithms, direct database access, or direct command-line tool execution. It should communicate with the backend through the Tauri bridge.

### `src-tauri/` - Input Adapter and Frontend-Backend Bridge

The `src-tauri/` folder acts as the bridge between the frontend and backend.

In the architecture, this folder maps to the **Input Adapter**. It translates UI actions into backend requests and returns backend responses to the frontend.

Typical responsibilities include:

- receiving frontend commands;
- validating or shaping request data;
- invoking backend use cases;
- returning results in a UI-friendly format; and
- forwarding progress, warnings, or errors back to the frontend.

Example flow:

```text
User clicks "Run Complete Analysis"
        |
Frontend sends a Tauri command
        |
src-tauri input adapter receives the request
        |
Backend application use case is invoked
```

### `backend/core/application/` - Application Layer

The `backend/core/application/` folder contains the application layer.

This layer coordinates what the system does. It should contain use cases, orchestration logic, and port definitions that describe what external capabilities the application needs.

Expected responsibilities include:

- use cases such as creating cases, registering evidence, verifying evidence, running analysis, and generating reports;
- the pipeline orchestrator that controls processing order;
- prerequisite checks before each pipeline stage;
- progress and failure handling; and
- ports that adapters implement.

The application layer should coordinate the workflow, but it should not contain the detailed forensic interpretation logic. That belongs in the domain layer.

Typical pipeline order:

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
Reconciliation
        |
Result Persistence
        |
Report Generation
```

### `backend/core/domain/` - Domain Layer

The `backend/core/domain/` folder contains FactumDB's core forensic logic.

This layer works with normalized forensic objects, not raw command-line output or UI data. It should remain independent from React, Tauri, SQLite, filesystem paths, and external tools.

The domain layer is responsible for:

- transaction grouping;
- record correlation;
- state reconstruction; and
- reconciliation between reconstructed log state and physical `.ibd` state.

Important domain concepts include:

- grouping binary-log events into committed, rolled-back, incomplete, or unresolved transactions;
- linking events to records using table identity, primary keys, composite keys, before images, and after images;
- replaying correlated events chronologically to reconstruct record history; and
- classifying final comparisons as exact, strong, partial, conflicting, unresolved, or unsupported.

### `backend/adapters/` - Infrastructure and Hexagonal Adapters

The `backend/adapters/` folder contains technology-specific implementations.

In Hexagonal Architecture, adapters sit outside the application core. They implement ports defined by the application layer and translate between external systems and FactumDB's internal models.

This layer may include adapters for:

- MySQL utilities such as `innochecksum`, `ibd2sdi`, `ibd2sql`, and `mysqlbinlog`;
- SQLite persistence;
- filesystem operations;
- SHA-256 hashing and verified working-copy creation;
- raw output preservation; and
- report generation.

Adapters should not decide the overall workflow order and should not contain domain reasoning. Their role is to connect FactumDB to external tools and infrastructure.

### `docs/` - Project Documentation

The `docs/` folder contains architecture, workflow, project planning, and supporting documentation.

Key files:

- [docs/Architecture.md](docs/Architecture.md) explains the finalized architecture and end-to-end workflow.
- Other documents may describe the complete project scope, work distribution, milestones, and evaluation approach.

### `images/` - Diagrams and Visual Assets

The `images/` folder stores architecture diagrams and other visual assets used by the documentation.

The high-level architecture diagram used in this README is:

```text
images/High level 2.png
```

## Dependency Rules

To keep the architecture clean, follow these dependency rules:

1. `frontend/` should communicate through `src-tauri/`, not directly with backend internals.
2. `src-tauri/` should act as an input adapter and should delegate business actions to backend use cases.
3. `backend/core/application/` should coordinate use cases, pipeline flow, ports, progress, and failures.
4. `backend/core/domain/` should contain forensic interpretation logic and should not depend on infrastructure.
5. `backend/adapters/` should implement application ports using external tools, SQLite, filesystem access, and report generation.

## Developer Guidance

When adding new functionality, place code according to its responsibility:

- UI screens, components, and frontend state belong in `frontend/`.
- Tauri commands and frontend-backend bridging belong in `src-tauri/`.
- Use-case coordination and pipeline orchestration belong in `backend/core/application/`.
- Forensic algorithms and domain services belong in `backend/core/domain/`.
- Tool execution, database storage, file access, and report generation belong in `backend/adapters/`.

If a module starts mixing responsibilities, move the logic closer to the layer that owns it. For example, parsing `mysqlbinlog` output belongs in an adapter, but deciding how decoded events are grouped into transactions belongs in the domain layer.

## Final Architecture Statement

FactumDB is structured so that each part of the project has a clear architectural role. The frontend supports investigator interaction, Tauri acts as the input bridge, the application layer coordinates the forensic pipeline, the domain layer performs forensic reasoning, and adapters connect the system to external tools and infrastructure. This separation supports repeatability, testability, maintainability, and realistic implementation within the project timeline.
