# Scenario 2: a deleted row recovered from the page

Scenario 1, then two more accounts, one of which is deleted. The reference copy was acquired on 2026-10-13 from MySQL 8.4.11 on macOS (the first copy was acquired on 2026-08-16 from MySQL 8.4.10 on Linux). `generate.sql` recreates it; the evidence files are never committed (see `.gitignore`).

## What it tests

| Check | Why it matters |
|---|---|
| The deleted account is still on the page | InnoDB only sets a delete flag; until purge runs, `ibd2sql --delete only` recovers the row |
| The remnant matches the logged `DELETE` | The `DELETE`'s before image and the remnant hold the same values, so each confirms the other |
| `mysql-bin.000001` and `000003` hold no row events | The first is the server's log from before the script ran, the last the one the script's final flush opened. Both are listed in the index and were copied, so they are not gaps |
| `mysql-bin.index` was copied | It proves no log is missing, so agreeing values are Exact |

## Creating and acquiring the evidence

On a test server with no other binlog history (see `../README.md`: the script replays scenario 1 itself), in a root MySQL session:

```sql
SOURCE <repo>/datasets/scenario2_delete/generate.sql
FLUSH TABLES finance.accounts FOR EXPORT;
```

Leave the session open and, in a second terminal, copy the tablespace:

```bash
mkdir -p <evidence>/scenario2_delete
cp <datadir>/finance/accounts.ibd <evidence>/scenario2_delete/
```

Back in the first terminal: `UNLOCK TABLES;` and `exit`. Then copy every binlog and the index:

```bash
cp <binlogdir>/mysql-bin.[0-9]* <binlogdir>/mysql-bin.index <evidence>/scenario2_delete/
```

Copy the tablespace soon after the delete. If purge removes the delete-marked row first, it is gone from the page and only the binlog records it - also a valid result, but not this scenario's.

## Expected results

Checked against the reference copy: `accounts.ibd`, `mysql-bin.000001` to `000003` and `mysql-bin.index` (hashes in `expected.json`).

| | Expected |
|---|---|
| Rows on the page | Live: `(101, 'Amal', 4000, 'suspended')`, `(103, 'Kamal', 3200, 'active')`. Deleted: `(102, 'Nimal', 7500, 'active')` |
| Row events | 3 `INSERT`, 2 `UPDATE`, 1 `DELETE`, all in `mysql-bin.000002` |
| Transactions | 6, all committed |
| Binlog coverage | Complete: the index lists `000001` to `000003`, and all three were copied |
| `accounts:101`, `accounts:103` | Every field Exact; each record Exact |
| `accounts:102` | Record presence Exact - the deleted remnant matches the logged deletion (R-RECON-023). Every field Exact against the `DELETE`'s before image; the record Exact |
