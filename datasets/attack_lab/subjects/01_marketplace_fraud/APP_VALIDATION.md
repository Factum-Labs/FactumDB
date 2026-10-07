# Actual app validation: 01_marketplace_fraud

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 16,271. Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Classification occurrences (nested record/field results):

```json
{
  "Unsupported": 3004,
  "Exact": 1116,
  "Unresolved": 247236,
  "Partial": 4
}
```

Finding rules:

| Rule | Count |
|---|---:|
| R-CORR-003 | 1 |
| R-CORR-010 | 1 |
| R-CORR-012 | 1 |
| R-CORR-020 | 2 |
| R-CORR-031 | 15700 |
| R-GRP-001 | 75 |
| R-GRP-013 | 73 |
| R-HIST-002 | 72 |
| R-HIST-003 | 72 |
| R-HIST-004 | 2 |
| R-HIST-010 | 3 |
| R-HIST-011 | 1 |
| R-HIST-012 | 15771 |
| R-RECON-001 | 417 |
| R-RECON-005 | 92210 |
| R-RECON-006 | 15707 |
| R-RECON-008 | 1500 |
| R-RECON-011 | 1 |
| R-RECON-020 | 71 |
| R-ROLL-002 | 69 |
| R-ROLL-004 | 2 |
| R-ROLL-005 | 15701 |
| R-ROLL-006 | 1 |
