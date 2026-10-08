# Scenario 2: a deleted row recovered from the page

Acquired on 2026-08-16 from MySQL 8.4.10: scenario 1, then two more accounts, one of which is deleted. `generate.sql` recreates it; the evidence files are never committed (see `.gitignore`).

## What it tests

| Check | Why it matters |
|---|---|
| The deleted account is still on the page | InnoDB only sets a delete flag; until purge runs, `ibd2sql --delete only` recovers the row |
| The remnant matches the logged `DELETE` | The `DELETE`'s before image and the remnant hold the same values, so each confirms the other |
| `mysql-bin.000002` to `000005` hold no row events | Server restarts left them; they are listed in the index and were copied, so they are not gaps |
| `mysql-bin.index` was copied | It proves no log is missing, so agreeing values are Exact |

## Creating and acquiring the evidence

On the test server, in a root MySQL session (`sudo mysql`):

```sql
SOURCE /home/user/factumdb/github/FactumDB/datasets/scenario2_delete/generate.sql
FLUSH TABLES finance.accounts FOR EXPORT;
```

Leave the session open and, in a second terminal, copy the tablespace:

```bash
mkdir -p ~/factumdb/evidence/scenario2_delete
sudo cp /var/lib/mysql/finance/accounts.ibd ~/factumdb/evidence/scenario2_delete/
```

Back in the first terminal: `UNLOCK TABLES;` and `exit`. Then copy every binlog and the index:

```bash
sudo cp /var/log/mysql/mysql-bin.[0-9]* /var/log/mysql/mysql-bin.index ~/factumdb/evidence/scenario2_delete/
sudo chown -R "$USER": ~/factumdb/evidence/scenario2_delete
```

Copy the tablespace soon after the delete. If purge removes the delete-marked row first, it is gone from the page and only the binlog records it - also a valid result, but not this scenario's.

## Expected results

Checked against the reference copy: `accounts.ibd`, `mysql-bin.000001` to `000006` and `mysql-bin.index` (hashes in `expected.json`).

| | Expected |
|---|---|
| Rows on the page | Live: `(101, 'Amal', 4000, 'suspended')`, `(103, 'Kamal', 3200, 'active')`. Deleted: `(102, 'Nimal', 7500, 'active')` |
| Row events | 3 `INSERT`, 2 `UPDATE`, 1 `DELETE`, in `mysql-bin.000001` and `000006` |
| Transactions | 6, all committed |
| Binlog coverage | Complete: the index lists `000001` to `000006`, and all six were copied |
| `accounts:101`, `accounts:103` | Every field Exact; each record Exact |
| `accounts:102` | Record presence Exact - the deleted remnant matches the logged deletion (R-RECON-023). Every field Exact against the `DELETE`'s before image; the record Exact |
