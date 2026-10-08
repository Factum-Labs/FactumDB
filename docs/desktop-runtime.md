# Desktop setup and workflow

## Run the application

The Windows x64 installer includes Python, the MySQL 8.4.11 utilities and
ibd2sql. Install and open FactumDB; **Settings** already contains the bundled
paths. **Use bundled tools** restores these paths after custom overrides.
No separate Python, MySQL server or Visual C++ runtime installation is needed.
The installer uses Tauri's WebView2 bootstrapper if WebView2 is missing.

The Ubuntu 24.04 x86-64 `.deb` installer also includes MySQL 8.4.11 utilities
and ibd2sql, with automatic tool paths. apt supplies Python and desktop libraries.
See [Linux bundling](linux-bundle.md) for installation, building in WSL, and
headless verification.

### Development

Install Node.js, Rust with the platform's Tauri build prerequisites, and Python
3.11 or newer. Install the root and frontend npm dependencies:

```powershell
npm install
npm --prefix frontend install
npm run bundle:windows:prepare
npm run tauri:dev
```

The app starts a persistent Python process automatically. Windows uses the
bundled interpreter when staged. Development without a bundle tries
`py -3.11`, then `py -3`, then `python`; other platforms use `python3`. To select a specific
interpreter, set `FACTUMDB_PYTHON` to its executable path before starting Tauri.
Python needs no third-party packages for application operation.

Tauri development watches the backend's `core`, `adapters` and `sidecar` folders
and restarts the app after changes. Reloading the frontend alone leaves the
persistent Python process running its previously loaded code.

Running the frontend's Vite server alone displays a desktop connection message.
Backend actions require the Tauri desktop app.

## Configure extraction utilities

Windows and Linux installers supply these paths automatically. Open **Settings**
to choose other tool versions when needed for your evidence. Without a bundle,
save paths to:

| Setting | Required utility |
| --- | --- |
| innochecksum | MySQL checksum utility executable |
| ibd2sdi | MySQL SDI extraction executable |
| ibd2sql | The external project's `main.py` script |
| mysqlbinlog | MySQL binary log utility executable |
| Python for ibd2sql | Python executable used to run that script |

Utilities must be compatible with the evidence's MySQL version. The application
records the executable or script hash, tool version, arguments, exit status and
exact output bytes for each extraction invocation. Tool-path settings persist in
`settings.json` under the application data directory.

Initial paths can also come from `FACTUMDB_INNOCHECKSUM_PATH`,
`FACTUMDB_IBD2SDI_PATH`, `FACTUMDB_IBD2SQL_PATH` and
`FACTUMDB_MYSQLBINLOG_PATH`. Deleted physical rows are opt-in in Settings.

## Examine a case

1. Sign in, then create a named case or open a saved case. The signed-in account
   supplies the examiner identity automatically.
2. Register evidence using Browse Files or an absolute file path. Supported names
   are `*.ibd`, `binlog.NNNNNN`, `mysql-bin.NNNNNN`, `binlog.index` and
   `mysql-bin.index`.
3. Verify a selected working copy, or let the pipeline verify all files.
4. Run the next stage or all ten stages. Stage results, attempt counts, errors,
   skipped-stage reasons and completion state come from the backend.
5. Review transactions, record histories, per-field reconciliation, coverage
   findings and extraction warnings. Expand correlation graphs for flagged
   records; graph nodes open the related transaction or record history.
6. Inspect tool runs in Provenance and read stdout/stderr previews. The backend
   checks the stored output hash before displaying bytes. Previews are limited
   to 256 KiB; complete outputs remain in the case workspace.
7. Export completed analysis to a new JSON file or CSV folder. Native dialogs
   select destinations; manually entered paths are also supported.

Cancellation takes effect at the next stage boundary. It does not terminate a
utility midway through a stage. Retry resumes a failed extraction or analysis
stage and retains the prior attempts. Verification failures require a new run.
Interrupted running stages are marked failed when the app next opens the case.

Registering more evidence clears current analysis results and marks prior runs
obsolete. Export remains disabled until the changed evidence has been analysed.
Evidence registration is blocked while a pipeline is active.

## Storage and packaging

Tauri's application data directory holds `catalog.db`, `settings.json` and
`cases/<case-id>/case.db`. Each case has separate working-copy and raw-output
folders. Original evidence files are read and hashed; extraction uses verified
working copies.

The Rust bridge serializes correlated JSON-lines requests to
`python -m sidecar.desktop --workspace <app-data>` on a worker thread. The Python
desktop composition wires the existing application use cases and domain services
to filesystem, tool and SQLite adapters. No forensic reasoning runs in React or
Rust.

`npm run bundle:windows` stages verified resources and builds the Windows x64
NSIS installer. See [Windows bundle build instructions](windows-bundle.md).
It includes the backend packages, SQLite schema, portable Python, extraction
utilities, licenses, a hash manifest and corresponding source archives.
Settings store only custom overrides, so bundled paths follow installation
location changes. Linux and macOS still need Python and external utilities.
JSON and CSV exports are implemented. PDF and HTML reporting remain future work.

## Verification

From `frontend/`:

```powershell
npm run build
npm run lint
npm run check:graph
npm run check:backend
```

`check:backend` requires pytest in the selected Python interpreter. It sends real
frontend-store commands through a substituted Tauri IPC boundary to a Python
process and SQLite, checks pipeline execution, cancellation and export, and
renders all screens against domain fixtures. External utility execution is
mocked; real parsers, hashes, working copies, repositories and domain services
run. This is not browser automation.

From `src-tauri/`, run `cargo test --lib` to exercise the native process transport,
error propagation, evidence verification and restart persistence.

From `backend/`, run
`py -3.11 -m pytest tests/application/test_desktop_runtime.py -q` on Windows
(`python3 -m pytest ...` elsewhere). The data-type tests use deterministic local
timezone fixtures for UTC and UTC+05:30, plus native host-timezone checks, so they
run on Windows without Unix-only `time.tzset`.
