# Scenario 3: text with a comma and an apostrophe

Scenario 2, then an account whose owner is `Perera, A. O'Brien`. The reference copy was acquired on 2026-10-13 from MySQL 8.4.11 on macOS (the first copy was acquired on 2026-09-04 from MySQL 8.4.10 on Linux). `generate.sql` recreates it; the evidence files are never committed (see `.gitignore`).

## What it tests

| Check | Why it matters |
|---|---|
| The two tools quote the name differently | `mysqlbinlog` writes `'Perera, A. O\'Brien'` and `ibd2sql` writes `"Perera, A. O'Brien"`. Both have to come back as the same text, or the values would look different when they are not |
| A comma inside a value | A parser that splits on commas would cut the name in two |
| Binlogs with no row events | `mysql-bin.000001` and `000003` hold none. Listed in the index and copied, so not gaps |

## Creating and acquiring the evidence

As scenario 2, with `scenario3_quotes` in place of `scenario2_delete` in the commands, again on a server with no other binlog history.

## Expected results

Checked against the reference copy: `accounts.ibd`, `mysql-bin.000001` to `000003` and `mysql-bin.index` (hashes in `expected.json`).

| | Expected |
|---|---|
| Rows on the page | Live: `(101, 'Amal', 4000, 'suspended')`, `(103, 'Kamal', 3200, 'active')`, `(104, 'Perera, A. O''Brien', 9000, 'active')`. Deleted: `(102, 'Nimal', 7500, 'active')` |
| Row events | 4 `INSERT`, 2 `UPDATE`, 1 `DELETE`, all in `mysql-bin.000002` |
| Transactions | 7, all committed |
| Binlog coverage | Complete: the index lists `000001` to `000003`, and all were copied |
| `accounts:101`, `103`, `104` | Every field Exact; each record Exact |
| `accounts:102` | As in scenario 2: Exact, against the remnant on the page |

## Notes

- `mysql-bin.000003` was the server's active binlog when it was copied. It still carries MySQL's "in use" flag, and `mysqlbinlog` warns that it "is either in use or was not closed properly". A copy taken after the server closed it would differ in that one byte (offset 22) and so have a different SHA-256, with identical events. Copying binlogs after `FLUSH BINARY LOGS` avoids this.
