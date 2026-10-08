# Dataset validity and realism audit

Audited on 2026-10-07, before implementing the backend repair plan.

The original evidence is valid MySQL output, with the documented acquisition
mutations. Independently generated, ordinary MySQL activity reproduces the core
correctness failures. They are not caused by invalid synthesized binary files.
However, these fixtures are simplified regression workloads, not faithful models
of five different production businesses. Calling them fully realistic was too
strong.

## Checks across all six original subjects

Used installed MySQL 8.0.43 `mysqlbinlog`, `ibd2sdi`, `innochecksum`, and the app's
bundled `ibd2sql`, together with the current adapters and domain services.

- All 61 acquired files still match their manifest sizes and SHA-256 hashes.
- All supplied tablespaces have readable schema metadata. Extracted live row
  counts match their recorded source counts, including the payroll file whose
  checksum was deliberately damaged.
- Supplied binlogs have complete event boundaries and valid event checksums.
  The clinic prefix ends before a transaction's terminator; valid individual
  events do not establish a complete transaction or complete acquisition.
- Parent references are consistent within the acquired scope. The clean control
  has no discrepancies between header totals, line totals and installment totals.
  Attack subjects have the deliberately altered relationships between amounts.
- The only checksum failure is the declared payroll disbursements page. Missing
  credit-union logs and logistics invoice/index evidence match the manifests.
- The logistics decoder emits 5,040 `SCHEMA_NOT_FOUND` warnings for unavailable
  invoice schema evidence. These are evidence-scope warnings, not proof of an
  invalid source database or a backend defect.

| Subject | Decoded row images | Interpretation of evidence condition |
|---|---:|---|
| Marketplace | 16,472 | Supplied files intact; privileged hidden writes injected |
| Credit union | 16,301 | Middle binlog deliberately withheld |
| Clinic | 16,478 | Final terminator and tail deliberately removed |
| Payroll | 16,472 | One page checksum deliberately altered |
| Logistics | 11,432 | Invoice tablespace and inventory index deliberately withheld |
| Clean marketplace | 15,550 | Intact acquisition; 15,500 live records and ordinary history |

These checks audit evidence validity and source consistency. They are not six new
complete desktop pipeline runs; the previous saved full runs cover marketplace
and clean control.

## Independent reproduction using ordinary commerce activity

`audit_realism.py` creates a separate MySQL database with four conventional
tables, foreign keys, a unique email constraint, composite line-item keys,
`VARCHAR` and `DECIMAL` columns, and matching order totals. Ordinary changes use
an account granted only SELECT, INSERT, UPDATE and DELETE. MySQL rejects both
that account's attempt to disable binlogging and an invalid parent deletion.
The generator's original business schema and bulk batches are not reused.

The script extracts real cold snapshots and decodes real binlogs. Focused domain
checks use actual decoded row images and physical records; selected histories
isolate downstream defects from the already confirmed grouping defect.

| Valid input or operation | Current backend result | Assessment |
|---|---|---|
| Ordinary multi-row inserts, small transactions | 13 row images become 6 grouped rows, with 7 duplicate findings | Row identity/grouping defect; large synthetic batches are unnecessary |
| Note-only MINIMAL update with unchanged key in before-image | `R-CORR-003`; legitimate changed note becomes Conflicting | Sparse-image correlation defect |
| Equal actual `VARCHAR(120)`, `VARCHAR(80)`, `VARCHAR(20)` and `DECIMAL(12,2)` values | All six tested columns fail comparability with `R-VAL-007` | Supported-type declaration normalization defect |
| Ordinary logged deletion; healthy supplied tablespace has no live row | Physical presence is unknown; verdict Unresolved | Presence model fails to distinguish absent row from absent evidence |
| Privileged unlogged deletion, healthy supplied tablespace | Logged presence versus unknown physical presence | Same presence defect, now with hidden deletion |
| Valid event-aligned prefix ending inside transaction | mysqlbinlog emits cleanup ROLLBACK; decoder reports rolled_back | Transaction-terminator interpretation defect |
| Privileged unlogged insertion | Unresolved, unexplained-row warning | Requires coverage proof before conflict classification; inventory alone is insufficient |

MySQL documents that multiple rows can share one event and that MINIMAL logging
retains identifying columns in before-images and changed columns in after-images:
[row logging and row-image options](https://dev.mysql.com/doc/refman/8.0/en/replication-options-binary-log.html).
These are normal supported database behaviors.

The performance issue is separate: bulk seeding amplifies repeated scans, but
the code's repeated scans are an implementation property, not corrupt evidence.
This audit does not claim a production latency benchmark or a measured fix.
The damaged-file presence gate still requires a focused regression during
implementation; the ordinary healthy-file reproductions do not test that gate.

## Limits on realism and attack interpretation

- All five attack businesses share essentially the same renamed retail-style
  schema. They do not model banking balances, clinical records, payroll tax rules
  or logistics workflows in industry-specific depth.
- Original schemas lack foreign keys and most business uniqueness constraints.
  Plausible names and values do not substitute for those constraints. The
  independent control demonstrates that the bugs also occur with constraints.
- Workloads run over a short interval with regular population patterns and no
  concurrent users, long retention, schema evolution or realistic workload mix.
  Clean INT/TEXT/DATE columns intentionally avoid comparison limitations; they
  are valid SQL, but less conventional than the independent control's types.
- Hidden writes use administrative privileges. They simulate an already
  privileged actor, not a normal application account gaining those privileges.
  Changes to a staff `role` field are application data, not MySQL GRANT changes.
- File omissions, the truncated tail and the checksum flip are controlled
  post-acquisition mutations. They test evidence loss and integrity handling;
  they do not establish an actual intrusion mechanism or a malicious cause.
- Logged malicious activity can reconcile Exact. Row consistency alone does not
  establish authorization. SQL injection entry points, SELECT-only exfiltration,
  credential theft and host/network activity need other evidence.
- A fabricated physical row is only a presence conflict if the relevant table's
  history is demonstrably covered from creation. A complete supplied binlog
  index alone does not prove that. Fixture ground truth establishes the injected
  action, but the app must reach its verdict using observable evidence.

The proposed correctness fixes remain justified. Expected missing-file,
damaged-page, sparse-image and unsupported-type warnings must remain explicit
evidence conditions. Broader production realism would require separate domain
schemas, mixed workloads and acquisition scenarios; it is not a prerequisite
for repairing the independently reproduced backend failures.

## Reproduce

From the repository root:

```powershell
py -3.11 datasets/attack_lab/audit_realism.py --mysql-bin 'C:/Program Files/MySQL/MySQL Server 8.0/bin'
py -3.11 datasets/attack_lab/verify_hashes.py
```

The audit uses a private temporary MySQL server and writes SQL, cold snapshots,
official decoded logs, diagnostics and `audit_results.json` under `.scratch/`.
It does not modify original subjects or backend source. The completed run used
`.scratch/realism-20261007-175602-016981/audit_results.json` (local ignored output).
