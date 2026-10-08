# Actual app validation: 03_clinic_interrupted_coverup

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 16,271. Elapsed: 83.48 seconds.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Engine revision: 2. Acceptance passed: **True**.

Record counts:

```json
{
  "Unsupported": 1,
  "Strong": 15442,
  "Unresolved": 59,
  "Partial": 300
}
```

Field counts:

```json
{
  "Unsupported": 901,
  "Exact": 15790,
  "Strong": 93172,
  "Unresolved": 247
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
- PASS: truncation_keeps_earlier_differences_unresolved
- PASS: final_transaction_incomplete
- PASS: unterminated_changes_not_applied
- PASS: truncated_coverage_visible
- PASS: cleanup_not_observed_rollback

Finding rules:

| Rule | Count |
|---|---:|
| R-CORR-010 | 1 |
| R-CORR-012 | 1 |
| R-CORR-020 | 2 |
| R-CORR-031 | 1 |
| R-COV-003 | 1 |
| R-COV-005 | 1 |
| R-GRP-001 | 75 |
| R-GRP-004 | 1 |
| R-HIST-002 | 15800 |
| R-HIST-003 | 15926 |
| R-HIST-004 | 21 |
| R-HIST-006 | 6 |
| R-HIST-007 | 10 |
| R-HIST-008 | 1 |
| R-HIST-009 | 15801 |
| R-HIST-010 | 301 |
| R-HIST-011 | 1 |
| R-HIST-012 | 15771 |
| R-RECON-002 | 93172 |
| R-RECON-004 | 48 |
| R-RECON-005 | 8 |
| R-RECON-006 | 181 |
| R-RECON-008 | 900 |
| R-RECON-020 | 15790 |
| R-RECON-022 | 10 |
| R-ROLL-003 | 15442 |
| R-ROLL-004 | 300 |
| R-ROLL-005 | 59 |
| R-ROLL-006 | 1 |
