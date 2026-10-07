# Actual app validation: 01_marketplace_fraud

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 16,271. Elapsed: 79.5 seconds.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Engine revision: 2. Acceptance passed: **True**.

Record counts:

```json
{
  "Unsupported": 1,
  "Exact": 15437,
  "Conflicting": 33,
  "Partial": 300,
  "Strong": 11,
  "Unresolved": 20
}
```

Field counts:

```json
{
  "Unsupported": 901,
  "Exact": 108890,
  "Conflicting": 53,
  "Strong": 78,
  "Unresolved": 188
}
```

Acceptance assertions:

- PASS: all_decoded_rows_accounted_for
- PASS: no_false_duplicate_rows
- PASS: keyless_table_visible
- PASS: unsupported_type_limitations_visible
- PASS: composite_key_continuity
- PASS: key_reuse
- PASS: minimal_updates_retained
- PASS: financial_rewrites_11_20
- PASS: contact_takeovers_31_40
- PASS: role_rewrites_8_9
- PASS: hidden_deletions_81_90
- PASS: fabricated_row_900001
- PASS: discontinuity_71

Finding rules:

| Rule | Count |
|---|---:|
| R-CORR-010 | 1 |
| R-CORR-012 | 1 |
| R-CORR-020 | 2 |
| R-CORR-031 | 1 |
| R-GRP-001 | 75 |
| R-HIST-002 | 15800 |
| R-HIST-003 | 15926 |
| R-HIST-004 | 21 |
| R-HIST-007 | 10 |
| R-HIST-008 | 1 |
| R-HIST-010 | 301 |
| R-HIST-011 | 1 |
| R-HIST-012 | 15771 |
| R-RECON-001 | 92753 |
| R-RECON-002 | 78 |
| R-RECON-003 | 42 |
| R-RECON-005 | 8 |
| R-RECON-006 | 180 |
| R-RECON-008 | 900 |
| R-RECON-011 | 347 |
| R-RECON-020 | 15790 |
| R-RECON-021 | 11 |
| R-RECON-031 | 42 |
| R-ROLL-001 | 33 |
| R-ROLL-002 | 15437 |
| R-ROLL-003 | 11 |
| R-ROLL-004 | 300 |
| R-ROLL-005 | 20 |
| R-ROLL-006 | 1 |
