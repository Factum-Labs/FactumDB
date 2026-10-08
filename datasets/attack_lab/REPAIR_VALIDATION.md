# Backend repair validation

Completed on 2026-10-08 (Asia/Colombo; recorded run timestamps are UTC) with
engine revision **2**, analysis format **2** and
JSON/CSV export format **2**. All six dataset acceptance checks pass.
Machine-readable counts and assertions are in [REPAIR_VALIDATION.json](REPAIR_VALIDATION.json).
Each subject's APP_VALIDATION report records its complete desktop backend run.

## Observed outcomes

| Subject | Verified outcome | Pipeline seconds |
|---|---|---:|
| [Marketplace](subjects/01_marketplace_fraud/APP_VALIDATION.md) | All hidden amount/contact/role rewrites, ten hidden deletions, fabricated row 900001 and discontinuity 71 detected; MINIMAL histories retained | 61.29 |
| [Credit union](subjects/02_credit_union_log_erasure/APP_VALIDATION.md) | Missing mysql-bin.000002 named; financial differences and fabricated row remain Unresolved; withheld key-change/reuse histories are not invented | 75.32 |
| [Clinic](subjects/03_clinic_interrupted_coverup/APP_VALIDATION.md) | Final transaction Incomplete, truncated coverage visible, held statuses and administrator role not applied as committed; earlier-file differences also retain tail uncertainty | 65.08 |
| [Payroll](subjects/04_payroll_page_damage/APP_VALIDATION.md) | Damaged tablespace identified; all 5,000 disbursement histories have conservative presence/value treatment | 78.29 |
| [Logistics](subjects/05_logistics_scope_gaps/APP_VALIDATION.md) | Missing index and invoice schema/tablespace evidence visible; no invoice physical values invented | 50.35 |
| [Clean control](subjects/06_clean_marketplace/APP_VALIDATION.md) | All 15,550 decoded changes accounted for; all 15,500 live records and 108,000 field rows Exact; no unexpected warnings | 65.31 |

All runs used the actual desktop command router, SQLite stores, installed MySQL
8.0.43 utilities and bundled ibd2sql. Deleted-row extraction was disabled as the
baseline checklist specifies. Assertion counts are separate from record and
field counts; repeated findings nested in several projections are not counted
as additional records or fields.

The 61 original evidence files still match their sizes and SHA-256 manifests.
Original SQL and EXPECTED_FINDINGS files were preserved. Their pre-repair backend
limitation notes are historical; APP_VALIDATION describes the corrected engine.
The [realism audit](REALISM_AUDIT.md) still applies: these are valid MySQL
regression fixtures with simplified business workloads.

## Implemented corrections

- Row identity includes the decoder-assigned row index. SQLite reads/lookups,
  grouping, histories, provenance and exports preserve the complete reference.
  Markers retain event positions and expand them into all rows in index order.
  Only repeated complete row references receive duplicate warnings.
- Utility-generated ROLLBACK cleanup no longer closes a transaction. Genuine
  terminators remain observable; missing terminators preserve incomplete status
  and coverage uncertainty, including for records last seen in earlier files.
- MINIMAL updates derive identity component by component from before-image keys
  and explicitly changed after-image keys. Unreadable changed keys are rejected;
  sparse images remain sparse.
- Comparison and reconciliation share base-type normalization. Original SQL
  declarations remain available; unsupported JSON/binary/float scope is unchanged.
- Absence in a successfully extracted, healthy tablespace differs from absent
  evidence. Presence comparisons honor damage, ambiguity and coverage gaps.
  Physical-only conflicts require creation observations and complete coverage;
  a complete inventory alone is insufficient. Unidentified keys prevent a table
  lifetime absence claim. No missing column values are synthesized.
- Per-stage primary-key indexes retain all physical candidates, including
  deleted remnants. Row/transaction and record lookup maps replace repeated
  scans. Loaded events carry their row provenance, and SQLite has a row-reference
  lookup index. Inventory/integrity lookups and desktop projections avoid
  repeated work.

## Compatibility and regressions

Existing cases preserve evidence, hashes, working copies, extraction records and
tool audit history. Incompatible derived results and normalization summaries are
invalidated, earlier pipeline runs become obsolete, and the UI case status reads
**Needs reanalysis**. Fresh complete analysis decodes the binlogs again, captures
creation observations and clears that status. Reopening a current case preserves
its corrected results.

The backend suite passes **1,053 tests** with **7 existing skips** for datasets
without enough history to permute ordering. Focused regressions cover multi-row
ordering/accounting, genuine duplicates, MINIMAL and composite keys, unreadable
keys, supported declarations and modifiers, unsupported types, healthy/missing/
damaged evidence, physical-only creation coverage, candidate ambiguity, truncated
tails, genuine versus generated rollback, indexed lookup counts and SQLite query
plans. Existing regressions cover key reuse and rollback reconstruction.

Upgrade/restart tests verify preserved evidence and tool history, obsolete runs,
fresh decoding, reanalysis status and versioned JSON/CSV exports. Core mypy checks
pass across 63 source files; the frontend production build passes. Reviewed
golden changes consist of row references/provenance and the intended damaged
presence classification; other fixture conclusions are unchanged.

Real JSON/CSV export verification on the completed clean case preserves all
15,550 row references and 108,000 reconciliation field rows. Local artifacts and
checks are under `.scratch/exports-08263a08/`, including `export_checks.json`.

## Performance

Compared with the saved pre-repair full runs on this machine:

| Dataset | Previous pipeline seconds | Corrected pipeline seconds | Improvement |
|---|---:|---:|---:|
| Marketplace | 574.11 | 61.29 | 9.37x |
| Clean control | 459.23 | 65.31 | 7.03x |

These are sums of stage attempt durations from recorded timestamps, excluding
final desktop projection/export time. The fresh complete commands took about
80 seconds for marketplace and 86 seconds for clean control, including final
projection. No pre-repair full timings existed for the other four subjects.
Lookup tests separately verify that indexing preserves ambiguity and bounds
physical-table reads rather than merely relying on a timing improvement.

## Remaining notices and warnings

Every non-info rule observed in the six runs is accounted for below. These are
expected attack evidence, intentional acquisition conditions, or documented
comparison/identity limitations, not remaining confirmed backend failures.

| Rules / adapter warnings | Explanation |
|---|---|
| R-CORR-010, R-CORR-012, R-HIST-011 | Deliberate composite-key rewrite and identity reuse; the missing credit-union log prevents observing those operations there |
| R-CORR-020, R-ROLL-006 | Intentionally keyless access-notes table; no invented InnoDB hidden identity |
| R-CORR-031 | Injected physical-only row; Conflicting only with sufficient creation coverage, otherwise Unresolved |
| R-COV-001, R-COV-002, R-COV-003, R-GRP-004 | Deliberately absent logistics inventory, withheld credit-union log or missing clinic terminator/tail |
| R-COV-005, R-HIST-009 | Acquisitions with coverage gaps cannot establish a complete snapshot comparison; truncated tails also limit earlier-file records |
| R-HIST-006 | Clinic changes have no observed commit and remain speculative |
| R-HIST-007, R-RECON-002, R-ROLL-003 | Ten intentional MINIMAL updates, or agreeing values under a coverage/discontinuity limitation |
| R-HIST-008 | Injected before-image discontinuity at business record 71 |
| R-HIST-010, R-RECON-008, R-ROLL-004 | JSON, binary and floating-point document fields remain outside validated comparison scope; supported parameterized types no longer receive these warnings |
| R-RECON-003, R-RECON-021, R-RECON-031 | Expected hidden rewrites, deletions and fabricated presence differences in intact covered evidence |
| R-RECON-004, R-RECON-022 | Differences could be explained by missing/truncated history and remain Unresolved |
| R-RECON-005 | Fabricated physical-only row has no logged column values; values are never filled in to force a comparison |
| R-RECON-006 | Logged deletions/hidden deletions leave no physical column values to compare, even when record presence is known |
| R-RECON-009 | Deliberately damaged payroll tablespace; both values and presence remain conservative |
| R-ROLL-005 | Record rollup exposes one of the documented missing-value, damage or coverage conditions |
| SCHEMA_NOT_FOUND (5,040 logistics row images) | Invoice schema cannot be recovered from the deliberately withheld tablespace; decoder reports each skipped row instead of assigning invented column names |

## Reproduce

```powershell
cd backend
py -3.11 -m pytest
py -3.11 -m mypy core
cd ..
py -3.11 datasets/attack_lab/verify_app.py --mysql-bin 'C:/Program Files/MySQL/MySQL Server 8.0/bin' --ibd2sql src-tauri/resources/runtime/windows/ibd2sql/main.py
py -3.11 datasets/attack_lab/verify_exports.py
py -3.11 datasets/attack_lab/verify_hashes.py
npm --prefix frontend run build
```

Failed or incomplete runs do not replace completed observed reports. A completed
run that fails an exact-key acceptance assertion records that failure and exits
unsuccessfully; fixture ground truth is not changed to make it pass.
