# Observed backend results

Acceptance passed: **True**. Engine revision: 2. Deleted-row extraction: off.

Import, analysis and result retrieval: **7.188 seconds**; pipeline stages: **5.82 seconds**. These are local backend measurements, not a timed GUI rehearsal.

Real extraction tools and desktop analysis backend; test device-verification port for an isolated local examiner. GUI and native device verification are not exercised.

Physical rows: 499. Decoded row events: 509. Committed/grouped transactions: 13.

## Record classifications

| Result | Records |
|---|---:|
| Exact | 493 |
| Conflicting | 5 |
| Strong | 2 |
| Unresolved | 1 |

## Field/presence comparisons

| Result | Comparisons |
|---|---:|
| Exact | 2615 |
| Conflicting | 7 |
| Strong | 11 |
| Unresolved | 14 |

Counts of records, comparison rows and findings measure different things; do not add them together.

## Selected records

| Record | Rollup |
|---|---|
| orders:10 | Exact |
| orders:20 | Conflicting |
| customers:31 | Conflicting |
| staff:7 | Exact |
| staff:8 | Conflicting |
| payments:25 | Conflicting |
| payments:30 | Unresolved |
| orders:900001 | Conflicting |
| orders:71 | Strong |
| orders:50 | Exact |
| orders:60 | Strong |
| orders:40 | Exact |

## Every non-Exact comparison

| Record | Field | Log | Physical | Result |
|---|---|---|---|---|
| customers:31 | email | customer031@example.invalid | shadow@example.invalid | Conflicting |
| orders:20 | amount_minor | 12000 | 999999 | Conflicting |
| orders:20 | status | settled | waived | Conflicting |
| orders:20 | destination | LOCAL-100020 | EXT-441199 | Conflicting |
| orders:60 | id | 60 | 60 | Strong |
| orders:60 | customer_id | 60 | 60 | Strong |
| orders:60 | amount_minor | 16000 | 16000 | Strong |
| orders:60 | status | settled | settled | Strong |
| orders:60 | destination | LOCAL-100060 | LOCAL-100060 | Strong |
| orders:71 | id | 71 | 71 | Strong |
| orders:71 | customer_id | 71 | 71 | Strong |
| orders:71 | amount_minor | 777777 | 777777 | Strong |
| orders:71 | status | settled | settled | Strong |
| orders:71 | destination | LOCAL-100071 | LOCAL-100071 | Strong |
| orders:71 | note | Receipt reissued | Receipt reissued | Strong |
| orders:900001 | record presence | absent | present | Conflicting |
| orders:900001 | id | not observed | 900001 | Unresolved |
| orders:900001 | customer_id | not observed | 12 | Unresolved |
| orders:900001 | amount_minor | not observed | 4700000 | Unresolved |
| orders:900001 | status | not observed | settled | Unresolved |
| orders:900001 | destination | not observed | EXT-441199 | Unresolved |
| orders:900001 | note | not observed | Unlogged fabricated order | Unresolved |
| payments:25 | record presence | present | absent | Conflicting |
| payments:25 | id | 25 | not observed | Unresolved |
| payments:25 | order_id | 13 | not observed | Unresolved |
| payments:25 | amount_minor | 5650 | not observed | Unresolved |
| payments:25 | channel | bank | not observed | Unresolved |
| payments:30 | id | 30 | not observed | Unresolved |
| payments:30 | order_id | 15 | not observed | Unresolved |
| payments:30 | amount_minor | 5750 | not observed | Unresolved |
| payments:30 | channel | card | not observed | Unresolved |
| staff:8 | role | clerk | administrator | Conflicting |

## Every finding rule emitted

| Rule | Title | Occurrences |
|---|---|---:|
| R-CORR-010 | Identity continued across a primary key update | 1 |
| R-CORR-012 | Key reused after deletion | 1 |
| R-CORR-031 | Physical record with no log events | 1 |
| R-GRP-001 | Transaction bounded by GTID | 13 |
| R-HIST-002 | Earliest state taken from the first observed event | 500 |
| R-HIST-003 | After-image applied | 507 |
| R-HIST-004 | Delete sets the record absent | 2 |
| R-HIST-007 | Partial row image | 1 |
| R-HIST-008 | Before-image disagrees with the reconstructed state | 1 |
| R-HIST-011 | Identity change | 1 |
| R-HIST-012 | Physical state appended | 499 |
| R-RECON-001 | Values agree | 2116 |
| R-RECON-002 | Values agree under limited coverage | 11 |
| R-RECON-003 | Comparable field values differ | 5 |
| R-RECON-005 | No log-derived value | 6 |
| R-RECON-006 | No physical value | 8 |
| R-RECON-020 | Record presence agrees | 499 |
| R-RECON-021 | Record presence conflicts | 2 |
| R-RECON-031 | Physical value matches no observed value | 5 |
| R-ROLL-001 | Record severity is the maximum over its fields | 5 |
| R-ROLL-002 | All fields agree | 493 |
| R-ROLL-003 | Every field agrees, under limited coverage | 2 |
| R-ROLL-005 | Evidence is insufficient for a conclusion | 1 |

## Acceptance checks

- PASS: all_acquisition_hashes_match
- PASS: 500_baseline_rows
- PASS: 499_live_rows_extracted
- PASS: hidden_amount_conflicting
- PASS: hidden_destination_conflicting
- PASS: hidden_status_conflicting
- PASS: hidden_email_conflicting
- PASS: hidden_role_conflicting
- PASS: hidden_deletion_conflicting
- PASS: unlogged_insert_conflicting
- PASS: logged_changes_agree
- PASS: logged_deletion_presence_agrees
- PASS: before_image_discontinuity_visible
- PASS: composite_key_change_visible
- PASS: key_reuse_visible
- PASS: minimal_change_retained_without_conflict
- PASS: rollback_not_invented
- PASS: all_decoded_row_events_retained
- PASS: no_missing_log_files
- PASS: no_adapter_warnings

The JSON companion contains all finding instances, adapter warnings, coverage, stage timings, selected records and every non-Exact record. Original SQL states the ground truth independently of this output.
