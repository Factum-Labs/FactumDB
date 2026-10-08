# Evaluation

How FactumDB was evaluated, what the results show, and what they cannot show. The tables themselves are in `evaluation-results.md`, which `datasets/evaluate.py` writes; nothing in that file is edited by hand. The numbers below are from the run recorded there.

## What was evaluated

| Part | Evidence | Scored against |
|---|---|---|
| The whole system: tools, adapters, case database, analysis | The four real scenarios in `datasets/`, acquired from MySQL 8.4 | Each scenario's `expected.json` |
| The domain engine on its own | The 12 synthetic golden datasets in `backend/tests/fixtures/` | Their `Expected` blocks, by `backend/tests/domain/test_evaluation_metrics.py` |

The expected results of the real scenarios were written from what each scenario did and from the rules in `correlation-rules.md`, not from FactumDB's output (see `datasets/README.md`).

## Method

`datasets/evaluate.py` takes each scenario that has an `expected.json`, checks every evidence file against its SHA-256, and runs the whole pipeline through the application's own services: case creation, registration, verified working copies, all ten stages with the real tools, and a SQLite case database. It then compares the stored result with `expected.json`.

Each scenario runs twice, each time in a new process with a new case database. Both runs must give the same fingerprint (a SHA-256 over the extracted rows, events, transactions, warnings, coverage and every verdict with its compared values). Time comes from the pipeline's stage records; memory is the peak resident size reported by the operating system, for FactumDB's process and for the largest tool process it started.

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
| Provenance | 80 of 80 observed log values and 95 of 95 observed page values link to their evidence; 984 of 984 references name the right tool run |
| Repeatability | Both runs identical in all four scenarios |
| Time | 0.2 to 0.7 s per case. `ibd2sql` takes the largest share (it runs twice per tablespace, for live and deleted rows); `mysqlbinlog` grows with the number of binlogs (24 in scenario 3); each analysis stage takes under 0.02 s |
| Memory | FactumDB's process peaks at 31 to 32 MB; the largest tool process at 31 MB |
| Record correlation | All 17 expected records identified |
| Transaction boundaries | Every row event in a transaction in scenarios 1 to 3; 14 of 19 in scenario 4 |
| Reconciliation | 57 of 112 field verdicts and 1 of 17 record verdicts as expected; 1 false alarm, 10 inconclusive, 44 wrongly unsupported |
| Domain engine, golden datasets | Transaction boundaries 16/16, correlation 15/15, reconciliation 20/20; no false positives or negatives |

The evidence is recovered, stored and traced back completely and the same way every time. The verdicts are not yet right.

## Why the verdicts differ

Every verdict that is not as expected traces to one of three causes, all in what real evidence contains that the golden datasets do not. They have been reported to the domain engine's owner.

| Cause | Where | Effect in the results |
|---|---|---|
| The supported-type check compares the declared type, such as `varchar(50)` or `decimal(12,2)`, with base names such as `varchar` | `backend/core/domain/services/record_reconciliation.py`, the first check in `_classify` | 44 fields Unsupported that should have been compared. Every record holding such a column becomes Partial, which is why only 1 of 17 record verdicts is as expected |
| The rows of a multi-row binlog event share one event reference (file and position), so the rows after the first are dropped as duplicates | `backend/core/domain/models/canonical.py`, `BinlogEvent.ref` | In scenario 4, 5 of 19 row events reach no transaction and no record. The rows left on the pages under the old keys of payment 3 and order item (100, 2) can then not be tied to their key changes: 10 inconclusive verdicts |
| An `UPDATE` logged with a partial row image is identified by its after image, which holds no key | `backend/core/domain/services/record_correlation.py`, `_key_event` | The update of payment 1's `note` is dropped, so the log side ends at `'first payment'` while the page shows `'checked'`: the one false alarm |

The golden datasets passed because their schemas use base type names, every event changes one row, and every row image is complete. Only real evidence showed the three gaps.

## What this evaluation cannot show

- **Missed conflicts.** In all four scenarios the pages agree with the logs, so a missed conflict cannot be counted: there is none to miss. A scenario with a change made while binary logging was off would measure it.
- **Scale.** The scenarios are small. A synthetic case of 60,000 events measured only the case database's own operations (see decision G in `sqlite-schema.md`), not the tools or the analysis.
- **Other setups.** One machine (Linux on WSL2), MySQL 8.4.10 and 8.4.11, one version of each tool. Other versions may print differently.
- **Time zones.** `TIMESTAMP` values are shown in the time zone of the machine reading them, by `ibd2sql` and by FactumDB alike. Both sides of a comparison therefore agree on any machine, but the text differs between machines, so the evaluation runs each scenario in the zone its expected values were read in (`timestamp_time_zone` in `expected.json`).

## Running it again

With the reference evidence in `~/factumdb/evidence` (each scenario in a folder of its own name, or directly in the folder) and `FACTUMDB_IBD2SQL_PATH` set or in `.env`:

```bash
python3 datasets/evaluate.py --evidence ~/factumdb/evidence --out docs/evaluation-results.md
```

A scenario whose files are missing, or are not the reference copies, is listed as not run instead of being scored.
