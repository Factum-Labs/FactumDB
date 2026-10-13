# Case exports: full JSON and investigator summary PDF

The desktop offers exactly two formats after analysis completes. Content follows
format, with no report-profile or section-selector controls. Redaction remains
an independent choice and defaults to a pseudonymized sharing copy.

Sharing policy version 3 preserves case names, examiner identity/profile, recorded actors,
tool names and versions, case/evidence/tool-run IDs, provenance hashes and
timestamps, and acquisition methods in both formats. Database identifiers and
values and evidence filenames are aliased. Notes, paths, commands, free-text
context and diagnostics are withheld. Original-values exports remain unchanged.

## Full case JSON

Desktop JSON exports use format version 3 and include every unique observation,
all six reconciliation classifications, complete live/deleted physical records,
decoded events, transaction groups, histories, speculative states, schemas,
intermediate analysis, warnings, acquisition/verification data and provenance.
Repeated observations retain their associations and occurrence counts.

Canonical objects appear once in `objects`; references use `{"$ref":"<kind>:<sha256>"}`.
The digest covers compact, UTF-8, sorted-key canonical content after redaction
when enabled. Different positions, row indices or contexts remain distinct.
Table rows keep references to canonical events, comparisons, sources and states.
Nested image keys remain evidence column names; tagged NULL, unobserved,
undecodable, decimal and datetime values retain their distinctions in original
exports. Redaction aliases evidence values and cannot support independent reanalysis.

Analysis tables use `analysis_<stage>_<member>`, with `index` and `value`.
An index of -1 denotes an empty array. `analysis_metadata` retains stage save
times. `expand_document()` reconstructs the version-2 evidence/analysis shapes;
reconstructible display strings and presentation duplicates are omitted.

Standalone `write_json(connection, case_id, path)` retains complete version-2
JSON compatibility. Passing `profile="full"` selects version 3. Partial profiles,
section selections and partial prepared documents are rejected by the writer.

## Styled summary PDF

The PDF is an A4 report with embedded local Unicode fonts, FactumDB teal/navy
headings, classification colors and vector bars, pale table rows, repeating
headers and page numbers. It contains readable prose and tables, never a JSON dump.

Its independent disk-backed projection includes:

- Case metadata, examiner notes, recorded acquisition and verification metadata,
  evidence inventory and hashes, and processing summaries.
- Case-wide and per-table record/field totals for all six classifications.
  Exact and Strong appear only as counts; no individual records or examples appear.
- Exceptional record classifications and field/presence comparisons grouped by
  table, classification, field and rule. Groups show distinct record references,
  observation counts, context variation counts and catalog explanations.
- Grouped warnings, schema/extraction coverage, integrity, transaction outcomes,
  reconstruction coverage, missing logs and limitations.
- Grouped evidence/tool-run/file references, recorded position endpoints and
  references without known positions. Endpoints do not imply continuous coverage.

Finding groups overlap, so their record counts must not be summed. Full command
arguments and diagnostic messages appear only in original-values JSON exports;
output hashes remain readable in sharing JSON. Values, images, histories and
speculative details remain in JSON, with database content aliased in sharing copies.
No arbitrary page or observation cap is used.

Summary aliases follow stable canonical traversal with category labels such as
`[TABLE-001]`, `[FIELD-001]` and `[SOURCE-001]`. Unknown
metadata remains explicitly unknown; unrecorded custody transfers are never inferred.
Redacted PDFs are pseudonymized and unsuitable for independent reanalysis.

## Preparation and preview API

`get_export_definitions` publishes the JSON/full and PDF/summary definitions.
`preview_export` and `export_case` accept case ID, format and redaction; export
also accepts path and optional preview token. Conflicting profile/section
arguments are rejected. Only JSON and PDF can be generated or registered.

`preview_export` with `progressive: true` returns `preparation_token`.
Polling `export_preview_status` advances preparation and returns `stage` and
`processed`, or the completed preview. Processed counts concern the current
stage and are not percentages. `cancel_export_preview` accepts the preparation
token; cancellation, replacement, expiry, lock/logout and shutdown clean up
projections, read-only source connections and generated preview artifacts.

Completed previews report format, detail, page count, size, manifest and coverage
counts. JSON shows a full-case manifest. PDF preparation generates the actual
PDF once; locally bundled PDF.js renders only the visible page, with navigation
and zoom. Its worker, fonts, CMaps and WASM assets are bundled for offline use.
`export_preview_pdf` accepts preview token, offset and length (maximum 262144
bytes) and returns a base64 chunk. Each request enforces authentication,
ownership, expiry and source/settings invalidation. Navigation does not reread
complete analysis or regenerate the PDF.

Saving PDF copies the exact reviewed bytes. JSON streams the frozen projection.
Every completed export records its actual creation time, actor, format version,
file size and SHA-256 in history. Destinations are never overwritten and source
case evidence is never changed. Historical unsupported formats and existing
files remain readable; their generation capabilities have been removed.

## Reproducibility and performance

Source ordering, grouping keys, rule explanations, fonts and layout are fixed.
The PDF records template and renderer versions; preview metadata retains the
font manifest in PDF metadata. Frozen preparation metadata produces identical PDF bytes.
Fresh exports may have new generation metadata and different hashes; unchanged
source data/settings retain the same substantive content and layout.

Large analysis is read through incremental SQLite blobs. Summary readers skip
unneeded containers and duplicate flat comparisons without decoding them.
Aggregation, deduplication and alias maps live in temporary SQLite; generation
never loads the whole case. The renderer buffers only the resulting summary PDF.

Run `py -3 scripts/benchmark_report_export.py --target-mb 800` with PDF
dependencies available to measure both formats. Results go to
`.bundle-cache/report-summary-benchmark.json`; synthetic files are cleaned up.
See [report-export-benchmark.md](report-export-benchmark.md) for measured results.
