# Report export benchmark

Measured locally on Windows with Python 3.11, using a disposable synthetic case
with 12,526 records, repeated large text values and 12 Conflicting comparisons.
The original analysis TEXT was 833,678,652 bytes; equivalent version-2 JSON was
945,139,832 bytes. No real case or AWS resource was used.

| Measurement | Investigator report | Full evidence export |
|---|---:|---:|
| JSON bytes | 44,875 | 25,150,722 |
| Reduction against version 2 | 99.995% | 97.339% |
| Projection preparation, with Python allocation tracing enabled | 23.432 s | 39.864 s |
| Peak Python allocations during generation | 586,446 bytes | 559,308 bytes |
| Peak process memory during generation | 32,239,616 bytes | 34,418,688 bytes |
| Preview text preparation | 0.562 s | 58.008 s |
| Cached preview page, average of 100 reads | 0.062 ms | 0.047 ms |
| Preview pages | 12 | 6,611 |
| Peak process memory including Unicode font loading/rendering | 81,047,552 bytes | 84,434,944 bytes |

The investigator export retained all 12 non-Exact comparisons and classification
totals for the complete source population. The full export retained all unique
observations and analysis details. Separate preservation tests expand full
version-3 exports back to their version-2 evidence and analysis shapes.

These reductions depend on this fixture's repeated large values and mostly Exact
comparisons. Cases containing unique values or many exceptions will produce
larger reports. Full preview preparation still scales with selected content;
page navigation uses stored text and does not reload source analysis.

Run `py -3 scripts/benchmark_report_export.py --target-mb 800` with the project's
PDF dependencies on `PYTHONPATH` to repeat the benchmark. Setup and each profile
run in separate processes so fixture allocation does not inflate generation
memory. The script writes measurements to `.bundle-cache/report-export-benchmark.json`
and removes its synthetic database and generated files afterwards.
