# Actual app validation: 06_clean_marketplace

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 15,500. Elapsed: 85.77 seconds.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Engine revision: 2. Acceptance passed: **True**.

Record counts:

```json
{
  "Exact": 15500
}
```

Field counts:

```json
{
  "Exact": 108000
}
```

Acceptance assertions:

- PASS: all_decoded_rows_accounted_for
- PASS: no_false_duplicate_rows
- PASS: 15500_live_records_exact
- PASS: no_unexpected_warnings

Finding rules:

| Rule | Count |
|---|---:|
| R-GRP-001 | 63 |
| R-HIST-002 | 15500 |
| R-HIST-003 | 15550 |
| R-HIST-012 | 15500 |
| R-RECON-001 | 92150 |
| R-RECON-011 | 350 |
| R-RECON-020 | 15500 |
| R-ROLL-002 | 15500 |
