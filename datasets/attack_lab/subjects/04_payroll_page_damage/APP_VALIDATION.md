# Actual app validation: 04_payroll_page_damage

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 16,271. Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Engine revision: 2. Acceptance passed: **True**.

Record counts:

```json
{
  "Unsupported": 1,
  "Exact": 10467,
  "Conflicting": 23,
  "Unresolved": 5000,
  "Partial": 300,
  "Strong": 11
}
```

Field counts:

```json
{
  "Unsupported": 901,
  "Exact": 74080,
  "Conflicting": 43,
  "Unresolved": 35008,
  "Strong": 78
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
- PASS: damaged_tablespace_visible
- PASS: damaged_presence_conservative
- PASS: damaged_values_conservative

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
| R-RECON-001 | 62933 |
| R-RECON-002 | 78 |
| R-RECON-003 | 42 |
| R-RECON-005 | 8 |
| R-RECON-008 | 900 |
| R-RECON-009 | 35000 |
| R-RECON-011 | 347 |
| R-RECON-020 | 10800 |
| R-RECON-021 | 1 |
| R-RECON-031 | 42 |
| R-ROLL-001 | 23 |
| R-ROLL-002 | 10467 |
| R-ROLL-003 | 11 |
| R-ROLL-004 | 300 |
| R-ROLL-005 | 5000 |
| R-ROLL-006 | 1 |
