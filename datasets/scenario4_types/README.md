# Scenario 4: data types, multi-row changes and composite keys

Synthetic evidence for testing what the adapters and the normalization have to get right beyond the single-key, integer-and-text tables of scenarios 1 to 3. `generate.sql` creates it; the evidence files themselves are never committed (see `.gitignore`).

## What each step tests

| Step | Change | What it checks |
|---|---|---|
| 1 | Three rows in one `INSERT` | One binlog event with several row images |
| 2 | One `UPDATE` matching two rows | A multi-row event: one position, two rows |
| 3 | `amount` 5000.00 → 4000.10 | `DECIMAL` kept exact - a float cannot hold 4000.10 |
| 4 | `fee` NULL → 2.000 | NULL handled as a value, not as "missing" |
| 5 | `payment_id` 3 → 30 | A primary key change |
| 6 | `payments` and `order_items` in one transaction | A transaction across two tables |
| 7 | Composite key: value change, key change, delete | `PRIMARY KEY (order_id, line_no)` |
| 8 | `binlog_row_image = MINIMAL` | A partial row image: only the key and the changed column are logged |
| 9 | `BLOB` and `JSON` columns | Types outside the validated scope are reported, never crash |
| 10 | Delete payment 2 last | A deleted row still on the page when the file is copied |

The `payments` table has one column of each common type: `INT`, `VARCHAR`, `CHAR`, `DECIMAL`, `ENUM`, `DATE`, `DATETIME`, `TIMESTAMP`, `TINYINT(1)` and `TEXT`. Each tool prints some of these differently, so both sides have to be turned into the same value before they can be compared.

## Creating and acquiring the evidence

On the test server (MySQL 8.4 with `binlog_format=ROW`), open a MySQL session as root in one terminal:

```bash
sudo mysql
```

At the `mysql>` prompt, create the scenario and lock the three tables for a consistent copy:

```sql
SOURCE /home/user/factumdb/github/FactumDB/datasets/scenario4_types/generate.sql
FLUSH TABLES shop.payments, shop.order_items, shop.attachments FOR EXPORT;
```

Leave that session open - the tables stay consistent only while it holds the lock. In a second terminal, copy the tablespaces:

```bash
mkdir -p ~/factumdb/evidence/scenario4_types
sudo cp /var/lib/mysql/shop/{payments,order_items,attachments}.ibd ~/factumdb/evidence/scenario4_types/
```

Back in the first terminal, release the lock: `UNLOCK TABLES;` then `exit`. Then copy every binlog and the index, so the inventory has nothing missing:

```bash
sudo cp /var/log/mysql/mysql-bin.[0-9]* /var/log/mysql/mysql-bin.index ~/factumdb/evidence/scenario4_types/
sudo chown -R "$USER": ~/factumdb/evidence/scenario4_types
```

## Notes

- Created on MySQL 8.4.11 (scenarios 1 to 3 were 8.4.10).
- The server deletes binlogs older than `binlog_expire_logs_seconds` (30 days by default) and removes them from `mysql-bin.index` too. When this scenario was acquired, `mysql-bin.000001` to `000023` had already gone that way, so the index started at `000024`. An inventory can only show logs missing from what the server still remembers: logs that expired before acquisition leave no trace in it.
- The newer binlogs and the index are readable by the `mysql` user only, so they are copied with `sudo`.
- The session time zone is fixed to `+05:30`, so the `TIMESTAMP` values are predictable.
- The delete is the last change, so payment 2 is likely still on the page as a delete-marked record. If purge has already removed it, that is a valid result too: the row is gone from the page and only the binlog records it.
- `mysql-bin.000024` is also in scenario 3. That copy was taken while it was the active log; this one after the server closed it, so the two differ in MySQL's one-byte "in use" flag and have different hashes, with identical events.

## Expected results

Checked against the copy acquired on 2026-10-05.

**Files.** The scenario's changes are all in `mysql-bin.000044`; `mysql-bin.index` lists `000024` to `000045` (22 files), and all of them were copied.

**How each tool prints the same value** - the reason for decision 8 in `docs/canonical-model.md`:

| Type | `mysqlbinlog` | `ibd2sql` |
|---|---|---|
| `DECIMAL(12,2)` | `5000.00` | `5000.00` |
| `ENUM` | `1` / `2` / `3` (position) | `'pending'` / `'paid'` / `'refunded'` |
| `DATE` | `'2026:10:01'` | `'2026-10-01'` |
| `TIMESTAMP` | `1790999100` | `'2026-10-03 09:15:00'` on a `+05:30` machine, `'2026-10-03 03:45:00'` with `TZ=UTC` |
| `BLOB` | `'\x89PNG\r\n\x1a\n'` | `0x89504e470d0a1a0a` |
| `DATETIME`, `CHAR`, `VARCHAR`, `TEXT`, `JSON`, `TINYINT(1)` | identical in both |

**Row images.** Step 1 is one event with three rows; step 2 one event with two. Step 8 logs only `@1=1` before and `@11='checked'` after.

**Deleted remnants.** `ibd2sql --delete only` returns more than the deleted rows: the page still held the versions that updates replaced, because purge had not run yet.

- `payments`: payment 2 as deleted (fee `2.000`, `paid`), two earlier versions of payment 2, payment 3 under its old key, and payment 1 as first inserted (`5000.00`, `pending`).
- `order_items`: `(101, 1)` as deleted, and `(100, 2)` under its old key.

**Transactions and warnings.** 14 committed transactions: 13 from the scenario, and one in `mysql-bin.000024` that inserted account 104 into `finance.accounts` (scenario 3). No tablespace of that table is in this evidence, so its columns cannot be named: one `SCHEMA_NOT_FOUND` warning, and the row is not stored as an event.

**Records and verdicts.** Binlog coverage is complete, so values that agree are Exact. Every column of payment 2's `DELETE` before image equals its deleted remnant on the page.

| Record | Expected |
|---|---|
| `payments:1` | Every field agrees, `note` = `'checked'` included, which step 8 logged. Exact or Strong, because step 8 was a partial row image (see `../README.md`) |
| `payments:2` | Deleted. The remnant matching the `DELETE`'s before image (fee `2.000`, `paid`) agrees on every field: Exact |
| `payments:30` | The row under its new key: every field Exact |
| `payments:3` | The page's copy under the old key, explained by the logged key change: agreeing (Exact or Strong), or merged into `payments:30` |
| `order_items:100\|1` | Every field Exact (`qty` 3) |
| `order_items:100\|3` | The row under its new key: every field Exact |
| `order_items:100\|2` | The old key's copy, explained by the key change: agreeing, or merged into `order_items:100\|3` |
| `order_items:101\|1` | Deleted. The remnant matches the logged deletion: every field Exact |
| `attachments:1` | `attachment_id` Exact; `content` (`BLOB`) and `meta` (`JSON`) Unsupported; the record Partial |

All 72 field verdicts are in `expected.json`. No field should be Conflicting or Unresolved: nothing in this scenario disagrees.
