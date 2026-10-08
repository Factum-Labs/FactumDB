# Scenario 1: one account, inserted and changed twice

The first evidence set, acquired on 2026-08-08 from MySQL 8.4.10: `finance.accounts` holding one account that was opened and then changed twice - the balance lowered from 5000 to 4000, then the account suspended. `generate.sql` recreates it; the evidence files are never committed (see `.gitignore`).

## What it tests

| Check | Why it matters |
|---|---|
| The page holds only the final row | The earlier values (5000, `active`) survive in the binlog alone: `innochecksum` counts 0 undo log pages, so nothing older is left in the tablespace |
| `@1` to `@4` named from the schema | `mysqlbinlog` prints column positions, not names |
| No `mysql-bin.index` | Nothing proves the binlogs are all there, so agreeing values may only be Strong |

## Creating and acquiring the evidence

On the test server, in a root MySQL session (`sudo mysql`):

```sql
SOURCE /home/user/factumdb/github/FactumDB/datasets/scenario1_update/generate.sql
SHOW BINARY LOGS;
FLUSH TABLES finance.accounts FOR EXPORT;
```

The scenario's changes are in the second-to-last file `SHOW BINARY LOGS` lists (the script flushes the logs before and after). Leave the session open and, in a second terminal, copy the tablespace and that one binlog - not the index, on purpose:

```bash
mkdir -p ~/factumdb/evidence/scenario1_update
sudo cp /var/lib/mysql/finance/accounts.ibd /var/log/mysql/mysql-bin.<number> ~/factumdb/evidence/scenario1_update/
sudo chown -R "$USER": ~/factumdb/evidence/scenario1_update
```

Then release the lock in the first terminal: `UNLOCK TABLES;` and `exit`.

## Expected results

Checked against the reference copy: `accounts.ibd` and `mysql-bin.000001` (hashes in `expected.json`).

| | Expected |
|---|---|
| Rows on the page | Live: `(101, 'Amal', 4000, 'suspended')`. No deleted rows |
| Row events | 1 `INSERT` and 2 `UPDATE`, all in `mysql-bin.000001` (GTIDs `…:5` to `…:7`) |
| Transactions | 3, all committed |
| Binlog coverage | Not provably complete: no index |
| `accounts:101` | Record presence Exact. `account_id`, `owner`, `balance` and `status` Strong. The record Strong |

Replaying the three events gives 5000/`active` → 4000/`active` → 4000/`suspended`, which is exactly the row on the page.
