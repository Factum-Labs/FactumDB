# Settings and workspace recovery

Settings now separates examiner profile, password changes, account preferences,
workspace storage, and the existing extraction-tool configuration.

## Account and session

Each local account has a display name, organization and examiner ID. These are
included as the exporting examiner's profile in future JSON/CSV exports. They
do not rename the login account or rewrite historical case examiners, evidence
actors or tool-run actors. Preferences and profiles are stored in the catalog's
users table, with an additive migration for existing accounts.

Changing a password requires the current password and matching new passwords
of 12–1024 characters. Password changes and unlocking share the persisted
failed-attempt throttle and verify the current OS identity.

Automatic locking defaults to 15 minutes. Available intervals are 1, 5, 15,
30 or 60 minutes, or Never. Lock is also available in the title bar.
The renderer immediately replaces the workspace with a password-only lock
screen. The backend denies case, settings, storage and export requests after
the timeout or an explicit lock. UI activity can extend an active session but
cannot unlock an expired one. Restart still requires normal sign-in.

An executing stage can finish while locked. The frontend stops submitting
further stages at the next boundary; unlock refreshes saved results. Native
backend requests are serialized, so a lock request during a long operation
is processed at its boundary. The screen hides immediately.

## Time display and reports

Users can select UTC, the OS local timezone, or a custom fixed UTC offset
between −12:00 and +14:00 (minute precision). The custom offset does not apply
daylight saving rules. Local formatting follows the OS timezone. Transaction
and record-history views show the selected timezone; timestamps show offsets.
Values without an established timezone are not converted.

JSON exports preserve exact timestamps in `tables` and add a `presentation`
section with the selected timezone, examiner profile and display-time values.
CSV exports preserve original columns, add `display_times.csv` keyed by table,
zero-based row and field, and explain the timezone in `about.txt`. Export file
hashes cover the added presentation data too.

## Storage, backup and restore

Open workspace folder opens the authenticated workspace in the native file
manager. Refresh usage calculates total usage, working copies, raw outputs,
reports, logs, databases/settings and a per-case breakdown. Free disk space is
shown separately. External original evidence is not counted.

Create workspace backup saves a new `.fdbbackup` ZIP archive outside the
workspace. It includes `catalog.db` (including accounts and preferences),
`settings.json` if present, and the complete `cases/` tree. Known SQLite databases
are snapshotted through SQLite's backup API so WAL contents are included without
copying transient WAL/SHM files. A manifest records the format, engine revision,
source workspace, creation time, file sizes and SHA-256 hashes. The archive is
verified before success is reported; existing backup files are never overwritten.

Backups are not encrypted. External original evidence files and bundled app/tool
binaries are not included. Cases without verified working copies still require
their original source files. Preserve those originals independently. Backup and
restore should be performed with only one FactumDB instance using the workspace.

Select backup to restore verifies its inventory, hashes and version, and shows
the creation time, case count and uncompressed size. Restore requires an explicit
replacement checkbox and the current account password. It stages the archive,
checks database integrity and case/catalog consistency, rebases operational
workspace paths, and retains historical source paths and provenance JSON.
Verified working-copy files are restored read-only. Unsafe archive paths,
checksum mismatches, newer-engine backups, insufficient disk space and backups
with no account bound to the current OS identity are rejected before activation.

The current workspace is renamed to a sibling `.rollback-<id>` folder before
the restored workspace is activated. Activation failures restore the original
workspace. A successful restore signs the user out and shows the rollback path;
sign in with credentials saved in the backup. Full workspace restore replaces
the catalog and accounts; it does not merge cases. Cross-device account migration
and encrypted or scheduled backups are not implemented.

## Verification

- `py -3.11 -m pytest` from `backend/`
- `npm run build`, `npm run lint`, `npm run check:backend`,
  `npm run check:settings-browser` from `frontend/`
- `cargo test --manifest-path src-tauri/Cargo.toml --lib` from the repository root

The settings tests exercise real SQLite snapshots/restores, rollback retention,
password changes, account isolation, backend lock expiry, malformed archives,
operational path rebasing and timestamp preservation. The frontend/backend check
also exercises profile/preferences persistence, lock-screen visibility, unlocking,
password changes and the complete existing analysis/export flow. Native file
dialogs require a desktop check.
