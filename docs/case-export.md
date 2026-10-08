# Case Export (JSON and CSV)

A case can be exported for checking outside FactumDB, as the workflow promises: *"the same case can also be exported as JSON or CSV for independent checking."* The code is in `backend/adapters/persistence/case_export.py`.

```python
from adapters.persistence.case_export import write_json, write_csv

write_json(connection, case_id, "exports/FDB-2026-014.json")
write_csv(connection, case_id, "exports/FDB-2026-014-csv/")
```

`connection` is the case database connection. Neither function overwrites an earlier export: `write_json` refuses an existing file and `write_csv` refuses an existing folder, because two exports mixed together could no longer be told apart.

## JSON - the exact record

One file holding every table's rows for the case, under `tables`:

`cases`, `evidence_files`, `tool_runs`, `integrity_results`, `schemas`, `schema_columns`, `physical_records`, `binlog_events`, `transactions`, `transaction_events`, `warnings`, `binlog_inventory`, `case_scopes`, `normalizations`, `analysis_results`, `table_creations`, `physical_extractions`. Desktop cases also include `pipeline_runs` when that table exists. The `reports` history stays in the case database.

- Format version 2 includes `engine_revision` and `analysis_format_version`. Binlog rows retain their `(source_file, log_position, row_index)` identity in JSON and CSV.
- Columns stored as JSON in SQLite (`values_json`, `before_json`, ...) are written as JSON, without the `_json` suffix.
- Column values keep the tags they are stored with, listed in the file's `value_tags`. `{"__decimal__": "4000.10"}` is the DECIMAL 4000.10, which a plain `4000.10` or `"4000.10"` could not say.
- Every row keeps its `evidence_id` and `tool_run_id`, and `tool_runs` has the exact command, tool version and executable hash, so any value can be followed back to the command that produced it.
- Rows are in a fixed order, so the same case always exports the same way. Only `exported_at` changes between exports.

This is the file to check against.

## CSV - for reading in a spreadsheet

| File | Contents |
|---|---|
| `evidence.csv`, `tool_runs.csv`, `integrity.csv`, `warnings.csv` | Those tables as they are stored |
| `rows_<db>.<table>.csv` | The rows found on the pages, one column per MySQL column, live rows first, then deleted ones |
| `events_<db>.<table>.csv` | Every row change, with `before.<column>` and `after.<column>` |
| `reconciliation.csv` | One line per compared field, once the analysis has run |
| `about.txt` | What the markers below mean |

A CSV cell is only text, so these markers keep apart things an empty cell would blur:

| Cell | Means |
|---|---|
| `\N` | SQL NULL (as MySQL writes it in its own exports) |
| `[not logged]` | A column a partial row image (`binlog_row_image=MINIMAL`) left out |
| `[undecodable: ...]` | A value the tool could not decode |
| empty, in `events_*.csv` | The event has no such image: an INSERT has no before image, a DELETE no after image |

Text starting with `=`, `+`, `-` or `@` is written with a leading `'`, so a spreadsheet shows it instead of running it as a formula. The evidence comes from a database that may have been tampered with, so its text is never trusted to be harmless (this is known as CSV or formula injection).

## Report history

Every export written to disk is recorded in the case database's `reports` table (see `sqlite-schema.md`, section 16):

- a version number, counted separately for JSON and for CSV;
- the SHA-256 and size of every file written, so a copy handed over can be checked later with `sha256sum`;
- `analysed_at`, which says which analysis the export contains, or that the analysis had not run yet.

The history is kept in the database, not inside the export, so the same case still exports the same way.

## Desktop workflow

The authenticated `export_case` sidecar command and the Report screen support JSON and CSV after the pipeline completes. Incomplete analysis and existing destinations are rejected. PDF and HTML report generation remain future work; their files can use the same history through `SqliteReportRepository.record()`.
