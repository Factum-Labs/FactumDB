# FactumDB

## 1. Project overview

FactumDB is a desktop digital forensics application for examining MySQL/InnoDB database evidence. It reconstructs record changes from binary logs and compares the reconstructed state with physical records extracted from `.ibd` tablespace files.

A tablespace shows physical records, while binary logs describe changes over time. FactumDB brings these sources together to help investigators identify agreements, conflicts, and gaps in the available evidence. Findings retain references to supporting evidence and extraction outputs.

The application is intended for digital forensic investigators, researchers, and students. The packaged utilities target MySQL 8.4; compatibility with other evidence versions depends on the selected utilities and evidence format. Analysis runs locally without a live MySQL server or AWS deployment.

## 2. Features

- **Local examiner accounts:** sign-up with native device verification, password sign-in, session locking, and examiner-scoped case access.
- **Case management:** create and reopen cases, register evidence, and maintain case notes.
- **Evidence integrity:** SHA-256 hashing and verified working copies, preserving original evidence during processing.
- **Evidence extraction:** InnoDB page validation, schema and physical-row extraction, and binary-log decoding, with pipeline progress and retry support.
- **Forensic analysis:** transaction grouping, record correlation, state reconstruction, and reconciliation against physical records.
- **Investigation views:** transaction timelines, record histories, correlation graphs, evidence gaps, and warnings.
- **Provenance and reporting:** extraction command records, preserved tool outputs, full JSON exports, and summary PDF reports.
- **Workspace settings:** extraction-tool configuration and workspace backup/restore subject to ownership checks.

## 3. Architecture and technologies

FactumDB uses a **layered modular monolith** with **hexagonal architecture** and a staged processing pipeline. The React interface communicates through Tauri with a persistent Python backend. SQLite stores case data locally.

| Component | Technologies and responsibility |
| --- | --- |
| `frontend/` | React 19, TypeScript, Vite, Tailwind CSS, and Zustand: investigator screens and frontend state. |
| `src-tauri/` | Tauri 2 and Rust: desktop integration, native authentication, and JSON-lines communication with the backend. |
| `backend/core/application/` | Python use cases, authentication, orchestration, and adapter contracts. |
| `backend/core/domain/` | Transaction grouping, record correlation, state reconstruction, and reconciliation rules. |
| `backend/adapters/` | Filesystem operations, hashing, SQLite persistence, extraction utilities, and report generation. |
| Extraction utilities | MySQL `innochecksum`, `ibd2sdi`, and `mysqlbinlog`, plus `ibd2sql`. |
| PDF generation | `fpdf2`, `uharfbuzz`, and bundled fonts. |

The application layer controls processing order, the domain layer interprets evidence, and adapters handle technology-specific operations. Forensic reasoning stays in the Python backend.

![FactumDB high-level architecture](images/High%20level%202.png)

See [Architecture](docs/Architecture.md) for the detailed design.

## 4. Prerequisites

### Building from source

| Requirement | Windows | Linux |
| --- | --- | --- |
| Build target | Windows x64 | Ubuntu 24.04 x86-64 |
| Source control | Git | Git |
| JavaScript tooling | Node.js 22.12+ with npm; Node.js 24 recommended | Native Linux Node.js 22.12+ with npm; Node.js 24 recommended |
| Rust | Current stable MSVC toolchain with `x86_64-pc-windows-msvc` | Current stable native Linux toolchain |
| Python | Python 3.11+ with the `py` launcher | Python 3.11+ as `python3` |
| Native build tools | Visual Studio 2022 Build Tools: Desktop development with C++, MSVC, and Windows SDK | Compiler and GTK/WebKit packages listed below |
| Initial sign-up | Windows Hello configured for the current Windows user | Desktop session with a running polkit authentication agent |

Initial builds need internet access for dependencies, pinned runtimes, extraction utilities, and corresponding source archives. Allow space for downloads, build outputs, and evidence working copies; packaged source archives alone occupy several hundred megabytes.

Windows staging requires the pinned Visual C++ redistributable DLLs from Visual Studio's `14.44.35112/x64/Microsoft.VC143.CRT` directory. If automatic discovery fails, set `FACTUMDB_VC_REDIST_DIR` to that directory. Different DLL versions fail the checksum check. See [Windows bundling](docs/windows-bundle.md) for details.

### Running an installer

The Windows installer includes Python, extraction utilities, and Visual C++ runtime DLLs. It can download WebView2 if missing. The Ubuntu `.deb` includes extraction utilities and PDF libraries; apt installs Python and required system libraries. Neither installer needs a MySQL server.

Earlier Ubuntu versions, ARM systems, and other Linux distributions are not verified targets. WSL can build the Linux package, but interactive sign-up requires a desktop authentication agent.

## 5. Build and run instructions

### Windows

After installing the prerequisites, open PowerShell:

```powershell
git clone https://github.com/Factum-Labs/FactumDB.git
cd FactumDB
npm ci
npm --prefix frontend ci
```

For an existing checkout, open PowerShell in its repository root and run the two `npm ci` commands.

#### Run in development mode

```powershell
npm run tauri:dev
```

The pre-launch script automatically stages missing Windows runtime resources. The first run may take time to download and verify them. Vite serves the interface at `http://localhost:1420`, Rust builds the desktop application, and the FactumDB sign-in window opens. Tauri starts the Python backend automatically.

Expected console output includes the Vite local URL and Rust compilation/startup messages. Exact timings and paths vary. Backend operations require the desktop window; opening the Vite URL in a browser alone is insufficient. Stop development with `Ctrl+C` in the terminal.

#### Build and run the installer

```powershell
npm run bundle:windows
```

This stages the pinned runtime, builds the application, and produces an NSIS `.exe` installer in:

```text
src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/
```

Open the generated installer, complete installation, and launch **FactumDB** from the Start menu. Expected startup is the sign-in window. Creating the first examiner account requires Windows Hello verification.

### Linux (Ubuntu 24.04 x86-64)

Install native Linux Node.js/npm and Rust as listed above, then install the system dependencies:

```bash
sudo apt update
sudo apt install build-essential curl file libwebkit2gtk-4.1-dev \
  libayatana-appindicator3-dev librsvg2-dev patchelf pkg-config libssl-dev \
  libaio1t64 libnuma1 polkitd pkexec python3 python3-pip git
```

Clone the repository and build from its root:

```bash
git clone https://github.com/Factum-Labs/FactumDB.git
cd FactumDB
python3 scripts/build_linux_bundle.py
```

The script downloads and verifies pinned tools, installs locked npm dependencies, builds in a native Linux workspace under `~/.cache/factumdb/`, and checks the resulting package. It copies the `.deb` and SHA-256 file to `dist/linux/` in the checkout. Successful output ends with lines identifying the installer and native build workspace.

The equivalent npm command is `npm run bundle:linux`. In WSL, use Linux `node`, `npm`, `cargo`, and `rustc`; Windows executables cannot build the Linux package.

#### Install and run

For the current project version:

```bash
sudo apt install ./dist/linux/FactumDB_0.1.0_amd64.deb
factumdb
```

If the version changes, use the filename printed by the build script. You can also open **FactumDB** from the desktop application menu. Expected startup is the sign-in window; a successful graphical launch does not require a particular terminal message. Initial sign-up prompts for native authentication through polkit.

See [Linux bundling](docs/linux-bundle.md) for additional packaging details.

### Runtime configuration

Packaged builds select bundled extraction tools automatically. In **Settings**, **Use bundled tools** restores these paths after custom overrides. For custom tools compatible with your evidence, configure `innochecksum`, `ibd2sdi`, `mysqlbinlog`, the `ibd2sql` project's `main.py`, and its Python interpreter.

Initial custom tool paths can also come from `FACTUMDB_INNOCHECKSUM_PATH`, `FACTUMDB_IBD2SDI_PATH`, `FACTUMDB_MYSQLBINLOG_PATH`, and `FACTUMDB_IBD2SQL_PATH`. For development, `FACTUMDB_PYTHON` selects a backend Python executable; a custom interpreter needs the dependencies in `backend/pyproject.toml` for PDF export.

Cases, settings, working copies, and results are stored in Tauri's application data directory. On Ubuntu this is `~/.local/share/lk.ac.uom.factumdb/`. Original evidence remains at its source location; extraction operates on verified working copies.
