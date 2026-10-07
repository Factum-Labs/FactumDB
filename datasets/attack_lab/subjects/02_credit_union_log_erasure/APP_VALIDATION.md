# Actual app validation: 02_credit_union_log_erasure

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 16,271. Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Engine revision: 2. Acceptance passed: **True**.

Record counts:

```json
{
  "Unsupported": 1,
  "Strong": 15324,
  "Unresolved": 178,
  "Partial": 300
}
```

Field counts:

```json
{
  "Unsupported": 901,
  "Exact": 15769,
  "Strong": 92986,
  "Unresolved": 460
}
```

Acceptance assertions:

- PASS: all_decoded_rows_accounted_for
- PASS: no_false_duplicate_rows
- PASS: keyless_table_visible
- PASS: unsupported_type_limitations_visible
- PASS: withheld_key_change_not_invented
- PASS: withheld_key_reuse_not_invented
- PASS: missing_log_named
- PASS: gap_explains_financial_differences
- PASS: fabricated_row_conservative

Finding rules:

| Rule | Count |
|---|---:|
| R-CORR-020 | 2 |
| R-CORR-031 | 2 |
| R-COV-002 | 1 |
| R-COV-005 | 1 |
| R-GRP-001 | 67 |
| R-HIST-002 | 15800 |
| R-HIST-003 | 15801 |
| R-HIST-008 | 1 |
| R-HIST-009 | 15802 |
| R-HIST-010 | 300 |
| R-HIST-012 | 15771 |
| R-RECON-002 | 92986 |
| R-RECON-004 | 229 |
| R-RECON-005 | 13 |
| R-RECON-006 | 187 |
| R-RECON-008 | 900 |
| R-RECON-020 | 15769 |
| R-RECON-022 | 31 |
| R-ROLL-003 | 15324 |
| R-ROLL-004 | 300 |
| R-ROLL-005 | 178 |
| R-ROLL-006 | 1 |
