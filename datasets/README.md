# Test datasets

- [Attack evidence lab](attack_lab/README.md): five simplified attack subjects and
  one clean control, with generated MySQL binlogs, `.ibd` tablespaces, exact
  expected-findings checklists, acquisition manifests and reproducible scripts.
  See the [validity and realism audit](attack_lab/REALISM_AUDIT.md) for independent
  reproductions and limits on production realism.
- [Scenario 4: types and composite keys](scenario4_types/README.md): the existing
  focused SQL scenario for adapter/type handling.

Generated binary evidence is kept locally and follows the repository's existing
Git ignore policy. See each dataset's instructions for reproduction and import.

Synthetic evidence for checking FactumDB against known answers. Each scenario folder holds:

| File | What it is |
|---|---|
| `generate.sql` | Creates the scenario on a MySQL 8.4 test server with `binlog_format=ROW` |
| `README.md` | What the scenario tests, how to acquire its evidence, and the expected results |
| `expected.json` | The same expected results, in a form a script can check a run against |

The evidence files themselves are never committed (see `.gitignore`: the repository is public, and git keeps a file forever). Each `expected.json` lists every file of the reference copy with its size and SHA-256, so a run can show it used exactly those files.

## The scenarios

| Scenario | What it tests | Evidence |
|---|---|---|
| `scenario1_update` | One account inserted and changed twice; no binlog index | 1 `.ibd`, 1 binlog |
| `scenario2_delete` | Scenario 1, two more accounts, and a deleted row recovered from the page | 1 `.ibd`, 3 binlogs, index |
| `scenario3_quotes` | Scenario 2, and an owner name with a comma and an apostrophe | 1 `.ibd`, 3 binlogs, index |
| `scenario4_types` | Common column types, multi-row events, primary key changes, a composite key, a partial row image, `BLOB` and `JSON` | 3 `.ibd`, 5 binlogs, index |

In all four, the pages agree with what the binlogs say happened. They measure whether the evidence is recovered correctly and whether agreement is reported as agreement, with no false alarms. None of them can measure whether a real disagreement would be missed, because none contains one.

## Acquiring the evidence

The reference copies were acquired on 2026-10-13 from MySQL 8.4.11 on macOS (Homebrew), by running each `generate.sql` on a fresh server. They replace the first copies, acquired on Linux from August to October, and match every expected row, event, transaction, warning and coverage result the first ones did; only the file list and hashes in `expected.json` changed. This also shows the scripts reproduce their scenarios.

Each scenario's README gives its steps. The paths differ by platform:

| | macOS (Homebrew `mysql@8.4`) | Ubuntu (`mysql-server`) |
|---|---|---|
| Root session | `mysql -u root` | `sudo mysql` |
| Tablespaces (`<datadir>`) | `/opt/homebrew/var/mysql` | `/var/lib/mysql` |
| Binlogs and index (`<binlogdir>`) | `/opt/homebrew/var/mysql` | `/var/log/mysql` |
| Copying | `cp`, as your own user | `sudo cp`, then `sudo chown -R "$USER":` on the copy |

Two rules matter more than the paths:

- **Start from a server whose binlogs hold nothing else.** Each `generate.sql` replays the earlier scenarios' changes itself (scenario 3 inserts account 101 again, for example), so logs left by an earlier run would count those changes twice. On a server that was used before, run `RESET BINARY LOGS AND GTIDS;` first - only ever on a test server.
- **Copy a tablespace while `FLUSH TABLES ... FOR EXPORT` holds its lock,** in the same session that ran the script, so the copy is consistent and purge has no time to remove a deleted row.

On macOS, MySQL sets `lower_case_table_names=2` because the file system ignores case. Every name in these scenarios is lowercase, so it makes no difference to the evidence.

## How the expected results were written

From what each scenario did - `generate.sql`, checked against the row events in the copied binlogs and the rows `ibd2sql` recovers from the pages - and from the classification rules in `docs/correlation-rules.md`. They were not taken from FactumDB's output: a result copied from the tool would only measure the tool against itself.

| Key in `expected.json` | Holds |
|---|---|
| `evidence` | Every file of the reference copy, with its size and SHA-256 |
| `columns` | Each table's columns in order, for reading `page_rows` |
| `page_rows` | The rows on the pages, `live` and `deleted`, in column order. `DECIMAL` values are text so no digit is lost; a `BLOB` is `"<binary>"`, because binary data is not decoded |
| `row_events` | How many row images of each kind the binlogs hold, per table |
| `transactions`, `warnings` | Committed transactions, and the warnings the evidence should cause |
| `coverage` | Whether the binlogs are provably complete, and which are missing |
| `records` | For each record (`table:key`), the expected verdict for the record (`rollup`) and for each field, as the list of verdicts the rules allow |

Values that agree are Exact only when the binlog index proves no log is missing (R-RECON-001); otherwise they are Strong (R-RECON-002). That is why scenario 1, which has no index, expects Strong.

Two cases allow more than one verdict:

- **A record changed through a partial row image** (scenario 4, payment 1). R-RECON-002 makes agreeing values Strong when a partial image is involved; but `binlog_row_image=MINIMAL` only leaves out columns that did not change, so Exact is defensible too. Either counts as correct. Conflicting or Unresolved would not.
- **A row left on a page under a key that was later changed** (scenario 4, payment 3 and order item `(100, 2)`). InnoDB keeps the old version delete-marked, and the logged key change explains it. It may be reported as its own record, agreeing, or merged into the record under the new key (`may_be_merged_into`).

## Running the evaluation

`evaluate.py` runs the whole pipeline on each scenario's reference evidence, twice, and scores the result against `expected.json`; see `docs/evaluation.md` for what it measures.

```bash
python3 datasets/evaluate.py --evidence <evidence folder> --out docs/evaluation-results.md
```
