# Actual app validation: 05_logistics_scope_gaps

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 11,301. Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Engine revision: 2. Acceptance passed: **True**.

Record counts:

```json
{
  "Unsupported": 1,
  "Strong": 10478,
  "Unresolved": 23,
  "Partial": 300
}
```

Field counts:

```json
{
  "Unsupported": 901,
  "Exact": 10800,
  "Strong": 63358,
  "Unresolved": 51
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
- PASS: missing_index_visible
- PASS: unavailable_invoice_schema_visible
- PASS: no_invoice_physical_values_invented

Finding rules:

| Rule | Count |
|---|---:|
| R-CORR-010 | 1 |
| R-CORR-012 | 1 |
| R-CORR-020 | 2 |
| R-CORR-031 | 1 |
| R-COV-001 | 1 |
| R-COV-005 | 1 |
| R-GRP-001 | 75 |
| R-HIST-002 | 10800 |
| R-HIST-003 | 10906 |
| R-HIST-004 | 1 |
| R-HIST-007 | 10 |
| R-HIST-008 | 1 |
| R-HIST-009 | 10801 |
| R-HIST-010 | 301 |
| R-HIST-011 | 1 |
| R-HIST-012 | 10801 |
| R-RECON-002 | 63358 |
| R-RECON-004 | 42 |
| R-RECON-005 | 8 |
| R-RECON-006 | 1 |
| R-RECON-008 | 900 |
| R-RECON-020 | 10800 |
| R-ROLL-003 | 10478 |
| R-ROLL-004 | 300 |
| R-ROLL-005 | 23 |
| R-ROLL-006 | 1 |
