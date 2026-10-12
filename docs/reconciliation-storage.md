# Reconciliation storage

Reconciliation conclusions use a compact internal JSON document in the existing
`analysis_results.result_json` column. Domain objects, desktop response shapes,
tagged JSON archives, CSV exports, and analysis semantics remain unchanged.

The storage header is `storage_format: "factumdb-reconciliation"` and
`storage_version: 1`. Its version is independent of the engine revision and
public analysis/export versions.

- `rows` stores each field comparison in its original order, with `finding_refs`.
- `records` stores record metadata, `field_refs`, and `finding_refs`.
- `finding_pool` stores findings interned by object identity, in first-encounter
  order while visiting rows, records, and top-level findings.
- Top-level `finding_refs` preserves the original case-level finding sequence.
- `coverage`, typed values, display strings, and provenance retain their existing
  representations. References are zero-based indexes; duplicates retain their order.

Saving encodes before entering the write transaction. Loading validates the
header, required properties, and references, decodes the pools once, and rebuilds
the domain result with shared field/finding objects. Invalid references and unknown
versions raise errors rather than returning partial conclusions.

Desktop projections read the compact document directly in SQLite. Comparison
details resolve only their selected findings in the same SQL statement. Archival
exports expand the compact document at the export boundary, retaining the old
external shape and its intentional duplication.

Documents without a storage marker use the legacy decoder. There is no bulk
migration: existing data is readable, and the next reconciliation save writes the
compact format. Older application versions cannot read new compact saves.

## Validation and benchmark

Compatibility tests compare compact and legacy desktop responses, preview metrics,
comparison details, archival tables, and reconciliation CSV bytes. Round-trip tests
cover all golden scenarios, tagged value types, shared and duplicate references,
empty results, missing properties, bad references, and save failures preserving
the previous result.

Run the local synthetic benchmark from `backend`:

```powershell
python checks/reconciliation_storage_benchmark.py --output checks/reconciliation_storage_results.json
```

It uses temporary WAL-mode SQLite databases and identical precomputed conclusions
for both formats. Cases are 2,500 records, 10,000 records, and 250 records with
40 updates each. Each format has one warm-up and five measured repetitions,
alternating order; results report median encoding/JSON generation, SQLite writing,
full domain loading, case preview, and last-comparison detail times. JSON byte
counts and compact/legacy ratios are also reported. Encoding excludes domain
analysis, writing excludes encoding, and loading includes reading and decoding.
Preview/detail timings exclude transport serialization. No real evidence or AWS
resources are used.

### Measured results — 12 October 2026

Local Windows run using Python 3.12.12 and SQLite 3.51.1; five measured repetitions
per format, after warm-up. Times
below are medians in seconds, shown as **legacy → compact**. The raw results are
in [reconciliation_storage_results.json](../backend/checks/reconciliation_storage_results.json).

| Fixture | JSON MB | Encoding | SQLite write | Full load | Preview | Last-field detail |
| --- | --- | --- | --- | --- | --- | --- |
| 2,500 records | 26.53 → 12.46 | 4.052 → 1.203 | 0.530 → 0.233 | 8.222 → 3.768 | 0.480 → 0.296 | 0.248 → 0.194 |
| 10,000 records | 106.40 → 50.07 | 15.874 → 6.958 | 2.223 → 1.279 | 36.366 → 18.480 | 2.587 → 1.321 | 1.523 → 0.789 |
| 250 records, 40 updates each | 5.89 → 2.86 | 0.684 → 0.327 | 0.109 → 0.061 | 1.851 → 0.893 | 0.136 → 0.075 | 0.080 → 0.047 |

JSON shrank 51–53%; encoding was 2.1–3.4× faster and full loading 2.0–2.2×
faster. Preview and detail queries improved for every fixture, so no measured
regression exceeded the 10% investigation threshold. Domain-result equality,
preview equality, and selected comparison-detail equality were checked during
every benchmark iteration. These synthetic storage measurements do not establish
a whole-pipeline speedup; reconciliation computation and expanded export size
remain unchanged.

Final verification: 1,233 backend tests passed, seven environment-dependent tests
were skipped, and 157 subtests passed. Ruff passed for the new codec, benchmark,
and storage tests; the diff passed whitespace checks.
