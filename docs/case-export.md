# Case Export (JSON and CSV)

## Investigator reports and full exports (version 3)

The desktop Report screen defaults to **Investigator report**, independently of
its redaction setting. It retains acquisition/verification and processing
metadata, evidence hashes, scope, all warnings and limitations, classification
totals by table, and individual typed comparisons for every non-Exact result.
Exact matches become counts. Relevant history and source observations support
the retained conclusions. Unknown values and locations remain unknown; recorded
processing metadata does not imply an unrecorded custody transfer.

**Full evidence export** retains every unique extracted observation and distinct
analysis result, including Exact comparisons, ordered events and speculative
states. Repeated copies and presentation-derived strings are omitted. Its size
still depends on the underlying evidence.

The existing section checkboxes remain. Optional additions, unchecked in the
investigator default, are `exact_matches`, `physical_records`, `binlog_events`,
`complete_timeline`, `complete_histories`, `complete_schemas` and
`intermediate_analysis`. The full default selects everything. Required metadata
and interpretation dependencies are automatically added; explicitly deselecting
default sections marks the result partial. Preview reports requested/effective
sections, automatically added sections, counts and prepared JSON bytes.

Desktop `preview_export` and `export_case` accept `profile: "investigator" |
"full"`, defaulting to `"investigator"`. `get_export_sections` returns section
IDs, labels, dependencies and profile defaults. Standalone `write_json`,
`write_csv` and `prepare_export` retain their version-2 defaults; pass an explicit
`profile` to obtain version 3. An explicitly prepared version-3 projection must
be closed by its caller; standalone writers close their own projections.

### Reference format

Version 3 has `tables` and an `objects` array. An object has `id`, `kind`, `value`,
`occurrences` and `associations` (origin and count). A structural `{"$ref": id}`
resolves through that array. IDs are deterministic content hashes of normalized
objects; redacted copies hash fresh aliases, not original sensitive values.
Occurrences count appearances in stored report structures, not independent
evidence observations.

- `comparison`, `source`, `finding`, `coverage`, `identity`, `event` and `state`
  objects are stored once. Large repeated evidence strings use `value` objects.
- `image` objects preserve evidence column names verbatim. Resolve only their
  child values, never interpret column names as report metadata. Tagged DECIMAL,
  datetime, unobserved and undecodable values retain their meanings.
- `analysis_<stage>_<member>` tables hold `index` and `value`. A null index means a
  scalar member; `-1` marks an empty array; other indices preserve array order.
  `analysis_metadata` retains stage/save times. Reconciliation records and the
  optional flat rows reference the same comparison objects.
- `binlog_events` rows hold source IDs, a canonical `event` reference and
  `stored_timestamp` preserving the original SQLite timestamp spelling. Canonical
  events carry database/table, row images, source position/row index and source
  provenance; grouped events reference the same object where their contents agree.
- Hashes live on canonical evidence/tool records; no duplicate exhaustive hash
  or provenance list is generated. Machine-readable timestamps are original;
  display timezone is declared once.

`adapters.persistence.investigator_export.expand_document(document)` is a
reference decoder for independent checking. It restores the legacy table and
analysis shapes except omitted display strings. This convenience decoder loads
its input into memory; generation and preview do not use it.

JSON uses compact encoding. Version-3 CSV has one file per canonical table plus
`objects.csv`; nested cells are JSON, with the same references and formula
injection protection. `about.txt` records the envelope and reference convention.
PDF and preview render the selected projection with locally bundled fonts.

Generation reads large analysis TEXT incrementally through SQLite's blob API.
The temporary projection, alias map and paginated text are disk-backed. Memory
scales with the largest individual record/history/transaction, rather than the
whole case. PDF generation additionally uses fpdf2's document buffer. Exports
remain local; no upload or AWS resource is involved.

Run `py -3 scripts/benchmark_report_export.py --target-mb 800` with the project's
PDF dependencies available for a reproducible synthetic benchmark. It records
baseline/output bytes, generation memory, preview preparation and cached page
latency in `.bundle-cache/report-export-benchmark.json`. The synthetic benchmark
contains repeated large values; its reduction is not a guarantee for other cases.

## Legacy standalone exports (version 2)

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
