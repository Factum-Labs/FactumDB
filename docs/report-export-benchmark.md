# Report export performance

The current report flow has full version-3 JSON and a separate grouped summary
PDF. Timings include projection preparation and file generation. PDF is rendered
once for preview; saving copies the prepared bytes rather than rendering again.

## Approximately 800 MB synthetic baseline

The generated fixture contains 12,526 records, including 12 non-Exact comparisons,
with repeated 8 KB values. Its pretty-printed version-2 baseline is 945,139,832
bytes; its stored reconciliation stage is 833,678,652 bytes. Each worker runs in
a fresh process so fixture construction does not inflate export memory.

| Measurement | Full JSON | Summary PDF |
|---|---:|---:|
| Output bytes | 25,150,722 | 19,842 |
| Generation time | 12.425 s | 5.894 s |
| Peak process working set | 32,874,496 bytes | 83,279,872 bytes |
| Pages | Not applicable | 3 |

JSON retains every unique observation and analysis result, including Exact
comparisons. PDF groups exceptional results and shows all classification totals;
no individual records are printed. These are different export contracts, not
interchangeable artifacts. No evidence was discarded to meet a size or page cap.

The synthetic reduction depends on repeated values and mostly Exact comparisons.
It does not predict reductions for cases with many unique observations or findings.
Memory above includes locally embedded Unicode fonts for PDF.

## Read-only development-case validation

A local case with 447,838,095 bytes of saved analysis was checked without changing
its source database or report history. It contains 15,803 classified records,
including 5,001 Unresolved, 300 Partial and 23 Conflicting records. All records
remain in full JSON; PDF aggregates them and their field/presence comparisons.

The expanded summary check, including record rollups and per-table totals,
completed in 56.638 seconds and produced 19 pages / 63,778 bytes, with a peak
working set of 84,692,992 bytes. This measurement ran alongside validation and
frontend build work. It retained 37 exceptional groups and 33 warning
categories with 110 grouped source associations. Compact aliases keep identifier width small without changing counts. The
summary also records analysis scope and in-scope/stored counts. Current
measurements are recorded in the local benchmark artifact.

Earlier archival previews completed preparation but printing their entire
canonical object graph was still unsuitable for PDF. The current summary builder
skips images and duplicate flat comparisons; no archive projection is rendered.

## Repeat the measurement

Run `py -3 scripts/benchmark_report_export.py --target-mb 800` with PDF dependencies
available. Results are written to `.bundle-cache/report-summary-benchmark.json`;
the synthetic database and generated files are removed afterwards. Generation
memory is bounded by individual parsed items and SQLite aggregation, not complete
case serialization. Renderer/template/font versions are fixed for reproducibility.
