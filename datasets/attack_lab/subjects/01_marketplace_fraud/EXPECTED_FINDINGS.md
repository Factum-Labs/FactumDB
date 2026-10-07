# Harbor Market: expected findings

All identities, addresses, documents and money are fictional. Currency is stored in minor units.

Database: `harbor_market`. Seeded rows: **16,300**. See `manifest.json` for acquired row counts, hashes and exact acquisition mutations; `baseline.sql` and `activity.sql` contain every generated change.

## Import

Create a separate case. Import every file in `ibd/` and `binlog/`, including `mysql-bin.index` when present. Do not import the SQL or manifests as evidence. Start with deleted-row extraction disabled; enable it in a second case to explore purge-dependent remnants.

## Injected errors and attack evidence (complete list)

| Check | Exact target / expected evidence | Expected handling |
|---|---|---|
| [ ] Hidden financial rewrite | `orders` IDs 11-20: amount_minor=99999999, destination=EXT-441199, status=waived; changes made with sql_log_bin=0 | Conflicting (R-RECON-003), with physical values absent from observed history (R-RECON-031) |
| [ ] Hidden privilege escalation | `staff` IDs 8 and 9: clerk to administrator without row events | Conflicting (R-RECON-003), with physical values absent from observed history (R-RECON-031) |
| [ ] Hidden contact takeover | `customers` IDs 31-40: email=shadow@example.invalid without row events | Conflicting (R-RECON-003), with physical values absent from observed history (R-RECON-031) |
| [ ] Hidden deletion | `payments` IDs 81-90 physically absent but still present in committed log state | Presence conflict R-RECON-021 with complete coverage, otherwise R-RECON-022; check live records, not purge-dependent remnants |
| [ ] Fabricated record | `orders` ID 900001 exists only in the tablespace | R-CORR-031; conflict with complete coverage, otherwise unresolved |
| [ ] Broken business totals | `orders` IDs 11-20, 50 and 71 disagree with original line/installment totals; parent IDs 41-45 and 301-310 lost installment rows; ID 900001 has no line/payment support | Ground-truth business errors for manual review: the current engine compares forensic evidence, not arbitrary cross-table accounting rules |
| [ ] Hidden history discontinuity | `orders` ID 71 silently changes amount_minor to 777777, then a logged note update exposes the new before-image | R-HIST-008; final values may agree, so the history warning is essential |
| [ ] Logged beneficiary diversion | `orders` IDs 101-160: destination=EXT-887711 | Visible update history; consistent logged attacks can reconcile Exact and need examiner review |
| [ ] Logged privilege escalation | `staff` IDs 7 and 19: role=administrator | Visible update history; the app does not determine who was authorized |
| [ ] Logged contact harvesting/redirect | `customers` IDs 201-230: email=collection@example.invalid | Visible mass-update history; data exfiltration itself is not proved by these files |
| [ ] Logged payment manipulation | `payments` IDs 401-420: channel=manual override | Visible update history |
| [ ] Logged destructive deletion | `payments` IDs 601-620 deleted | Deletion histories; a matching deletion is not a reconciliation conflict |
| [ ] Primary-key rewrite | `order_lines` key (10,2) becomes (10,3) | R-CORR-010 and R-HIST-011; composite key correlation R-CORR-002 |
| [ ] Identity reuse | `orders` ID 50 deleted and reinserted with reference REUSED-000050 | R-CORR-012; interval of absence followed by a new row |
| [ ] Partial images | `orders` IDs 301-310 get note-only updates under MINIMAL | R-HIST-007; omitted columns must not become NULL/zero; Strong or other conservative result where applicable |
| [ ] No primary key / audit redaction | `access_notes`: 500 rows, operator-7 actions rewritten | R-CORR-020, Unsupported identity; never invent an InnoDB hidden row ID |
| [ ] Rich/unsupported values | `documents`: 300 rows with VARCHAR(120), BLOB, JSON, DECIMAL(12,2), DOUBLE; document 1 altered | R-RECON-008 / decode warnings as applicable; do not manufacture equality for unsupported values |

## Benign controls mixed into the attack

`orders` 91 was updated inside a rolled-back transaction: its durable amount stays unchanged. MySQL does not persist those row events, so the app cannot infer the attempted write or invent a rollback history. Unaffected rows have normal names, regional branches, dates, business references and two installment entries that sum to the header amount. SQL sources are ground truth for the scenario, not evidence supplied to the app.

## Subject-specific evidence error

Complete acquisition: all supplied files are structurally valid. The hidden-write differences should be actionable conflicts. This subject isolates semantic tampering from file corruption and coverage loss.

Exact byte-level modifications / omissions:

```json
[]
```

## Limits of the evidence

These fixtures cover row manipulation, fraud, privilege-field changes, audit tampering, anti-forensic log loss, transaction boundaries, page damage, schema scope, partial images and unsupported types. They do not prove SQL injection, credential theft, network exfiltration, denial of service, execution of malware, server-account GRANT changes, or an attacker's identity: those require application/access/network/host logs or system-table evidence. A row-based binlog generally cannot recover the original injected SQL. Keyless and rich-type tables are ordinary schema features; their warnings describe analysis limitations, not attacks. Purge-dependent deleted remnants are optional observations, never mandatory pass criteria.

Known current-engine limitation: multi-row inserts legitimately share a binlog event position. R-GRP-013 currently discards all but the first image at that position, so many baseline histories and intended attack comparisons can be missed. The checklist above states the correct acceptance behavior, not a promise that the current implementation already passes it. See the lab README and any APP_VALIDATION.md report for observed results.
