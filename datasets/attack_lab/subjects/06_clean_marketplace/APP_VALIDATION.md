# Actual app validation: 06_clean_marketplace

Pipeline complete: **True**. Deleted-row extraction: off. Physical rows extracted: 15,500. Report recovered from the stored validation case; stage timestamps are in APP_VALIDATION.json.

These observations are from the current backend and installed tools, not assumed expected results. A stopped pipeline or a clean-control warning is an app/tool limitation to investigate; do not change fixture ground truth to conceal it.

Classification occurrences (nested record/field results):

```json
{
  "Exact": 1008,
  "Unresolved": 245992
}
```

Finding rules:

| Rule | Count |
|---|---:|
| R-CORR-031 | 15437 |
| R-GRP-001 | 63 |
| R-GRP-013 | 63 |
| R-HIST-002 | 63 |
| R-HIST-003 | 63 |
| R-HIST-012 | 15500 |
| R-RECON-001 | 377 |
| R-RECON-005 | 92122 |
| R-RECON-006 | 15437 |
| R-RECON-011 | 1 |
| R-RECON-020 | 63 |
| R-ROLL-002 | 63 |
| R-ROLL-005 | 15437 |
