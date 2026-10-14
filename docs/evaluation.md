# Evaluation

How FactumDB was evaluated, what the results show, and what they cannot show. The tables themselves are in `evaluation-results.md`, which `datasets/evaluate.py` writes; nothing in that file is edited by hand. The numbers below are from the run recorded there.

## What was evaluated

| Part | Evidence | Scored against |
|---|---|---|
| The whole system: tools, adapters, case database, analysis | The four real scenarios in `datasets/`, acquired from MySQL 8.4.11 | Each scenario's `expected.json` |
| The domain engine on its own | The 12 synthetic golden datasets in `backend/tests/fixtures/` | Their `Expected` blocks, by `backend/tests/domain/test_evaluation_metrics.py` |

The expected results of the real scenarios were written from what each scenario did and from the rules in `correlation-rules.md`, not from FactumDB's output (see `datasets/README.md`).

The reference evidence was acquired again on 13 Oct 2026: each scenario was recreated from its `generate.sql` on a fresh MySQL 8.4.11 server and acquired the same way as before. In each `expected.json` only the evidence list, its hashes and the acquisition details changed. The expected rows, events, transactions, warnings and coverage were left as they were, and the new evidence matches every one of them, so two acquisitions on different machines give the same results.

## Method

`datasets/evaluate.py` takes each scenario that has an `expected.json`, checks every evidence file against its SHA-256, and runs the whole pipeline through the application's own services: case creation, registration, verified working copies, all ten stages with the real tools, and a SQLite case database. It then compares the stored result with `expected.json`.

Each scenario runs twice, each time in a new process with a new case database. Both runs must give the same fingerprint (a SHA-256 over the extracted rows, events, transactions, warnings, coverage and every verdict with its compared values). Time comes from the pipeline's stage records; memory is the peak resident size reported by the operating system, for FactumDB's process and for the largest tool process it started. Linux reports that size in kilobytes and macOS in bytes, and the script converts both to MB.

| Measure | Counted as |
|---|---|
| Page rows as expected | Rows recovered with every value as expected, live and deleted separately |
| Row event counts as expected | Per table and kind (`INSERT`, `UPDATE`, `DELETE`), the count of row images matches |
| Row events placed in a transaction / linked to a record | Out of the row events stored |
| Field and record verdicts as expected | The verdict is one the rules allow for that field or record |
| False alarm | Conflicting where the evidence does not disagree |
| Missed conflict | Not Conflicting where the evidence does disagree |
| Inconclusive | Unresolved where the values agree |
| Wrongly unsupported | Unsupported for a column whose type is in the validated scope |
| Provenance | Observed values whose verdict links to the event or page row they came from; references naming the tool run, tool and file that really produced the data |

## Results

| Area | Result |
|---|---|
| Extraction and decoding | All 20 page rows with every value, all 18 row event counts, all 30 committed transactions, the expected warning and the binlog coverage of each scenario: 100% |
| Provenance | 80 of 80 observed log values and 95 of 95 observed page values link to their evidence; 1,324 of 1,324 references name the right tool run |
| Repeatability | Both runs identical in all four scenarios |
| Time | 0.34 to 0.75 s per case. `ibd2sql` takes the largest share, because it runs twice per tablespace, for live and deleted rows; each analysis stage takes under 0.02 s |
| Memory | FactumDB's process peaks at 35 to 38 MB; the largest tool process at 18 MB |
| Record correlation | All 17 expected records identified |
| Transaction boundaries | Every row event in a transaction, in all four scenarios (35 of 35) |
| Reconciliation | 97 of 112 field verdicts and 15 of 17 record verdicts as expected; no false alarms, 15 inconclusive, none wrongly unsupported |
| Domain engine, golden datasets | Transaction boundaries 16/16, correlation 15/15, reconciliation 20/20; no false positives or negatives |

Scenarios 1 to 3 are as expected in every measure. Every verdict that is not as expected is in scenario 4, and they all have the same cause, described below.

## What the first run found

The first run, on 8 Oct 2026 at commit `e7af06a`, recovered and traced the evidence just as completely, but most of its verdicts were wrong. It traced them to three causes in the domain engine, all things that real evidence contains and the golden datasets did not. They were reported to the domain engine's owner and fixed in commit `33c0a39`:

| Cause found by the first run | Effect then | Now |
|---|---|---|
| The supported-type check compared the declared type, such as `varchar(50)` or `decimal(12,2)`, with base names such as `varchar` | 44 fields wrongly Unsupported, so only 1 of 17 record verdicts was as expected | None wrongly unsupported; 15 of 17 record verdicts as expected |
| The rows of a multi-row binlog event shared one event reference, so the rows after the first were dropped as duplicates | 14 of 19 row events in scenario 4 reached a transaction | 19 of 19 |
| An `UPDATE` logged with a partial row image was identified by its after image, which holds no key | 1 false alarm, on payment 1's `note` | No false alarms |

The golden datasets had passed because their schemas use base type names, every event changes one row, and every row image is complete. Only evidence from a real server showed the three gaps.

## The verdicts that still differ

| Records | What happens | What the rules allow |
|---|---|---|
| `payments:3` and `order_items:100\|2` in scenario 4 | Their primary keys were changed, 3 to 30 and (100, 2) to (100, 3). InnoDB keeps the old versions on the page, delete-marked. FactumDB reports each old version as a record of its own with every field Unresolved: the log has no value for the old key after the change, while the page still shows the old row | Agreeing, because the logged key change explains the leftover row, or merged into the record under the new key (`may_be_merged_into` in `expected.json`) |

This accounts for all 15 inconclusive field verdicts and both record verdicts that differ. It has been reported to the domain engine's owner. Nothing is reported as Conflicting, so it does not create a false alarm, but two leftover rows that the log explains are left unexplained.

## Coverage of the proposal's evaluation plan

The project proposal planned datasets of the following kinds:

| Planned in the proposal | Covered by |
|---|---|
| Single-row insert, update and delete | Scenarios 1 and 2 |
| A multi-table committed transaction | Scenario 4: one transaction updates `payments` and inserts into `order_items` |
| A rolled-back transaction | `attack_lab` subjects 01, 02 and 06 |
| Primary-key updates and a composite-key table | Scenario 4 |
| A deleted record absent from the current state | Scenarios 2 and 3 |
| A deliberately missing binary-log file | `attack_lab` 02 (a middle log withheld) and 03 (the log tail missing) |
| A deliberately corrupted InnoDB page | `attack_lab` 04 |
| Mismatched `.ibd` and binlog snapshots, for conflict detection | `attack_lab` 01 |
| Two or more concurrent sessions with interleaved transactions | Golden dataset ds05 only, which is synthetic. No real-evidence dataset has it |

`datasets/attack_lab` was prepared by the domain engine's owner. Its results are recorded in each subject's `APP_VALIDATION.md`, from MySQL 8.0.43 evidence that is not stored in the repository, so they were not re-run for this evaluation.

## What this evaluation cannot show

- **Missed conflicts.** In all four scenarios the pages agree with the logs, so a missed conflict cannot be counted here: there is none to miss. Only `attack_lab` subject 01 holds a real disagreement.
- **Concurrent sessions on real evidence.** Grouping events from interleaved sessions is tested only on the synthetic golden dataset ds05.
- **Scale.** The scenarios are small. The attack-lab subjects hold about 16,000 rows each, export at scale is measured in `report-export-benchmark.md`, and a synthetic case of 60,000 events measured the case database's own operations (see decision G in `sqlite-schema.md`).
- **Other setups.** This run used one Mac (macOS on Apple Silicon) with MySQL 8.4.11 and one version of each tool; the first run used Linux on WSL2 with MySQL 8.4.10 and 8.4.11. On macOS, MySQL sets `lower_case_table_names=2` because the file system ignores case; every name in the scenarios is lowercase, so the stored names are the same. Other versions may print differently.
- **Time zones.** `TIMESTAMP` values are shown in the time zone of the machine reading them, by `ibd2sql` and by FactumDB alike. Both sides of a comparison therefore agree on any machine, but the text differs between machines, so the evaluation runs each scenario in the zone its expected values were read in (`timestamp_time_zone` in `expected.json`).

## Running it again

With the reference evidence in one folder (each scenario in a folder of its own name, or directly in the folder), the MySQL 8.4 tools on the `PATH`, Python 3.11 or newer, and `FACTUMDB_IBD2SQL_PATH` set or in `.env`:

```bash
python3 datasets/evaluate.py --evidence <evidence folder> --out docs/evaluation-results.md
```

A scenario whose files are missing, or are not the reference copies, is listed as not run instead of being scored.
