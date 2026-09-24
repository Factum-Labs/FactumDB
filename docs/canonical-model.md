# FactumDB Canonical Model

## Why we need this

We use four different tools to read the evidence and every one of them gives output in a different format. You can't compare them directly - it is like getting four receipts in four different currencies, you have to convert everything into one currency before you can add anything up. The canonical model is that one currency. Each adapter converts its tool's output into these objects, and everything after that point (the domain services and the UI) only works with these objects, never with raw tool output. This document is therefore the contract between the layers: the adapters produce these shapes, and the domain services can depend on them. The models below are the ones listed in `Architecture.md` section 5.9.

All the examples here come from the project's test evidence (the `finance.accounts` table) rather than invented values.

---

## 1. Schema

From the `ibd2sdi` adapter. Describes one table.

| Field | Type | Example |
|---|---|---|
| `database` | str | `"finance"` |
| `table` | str | `"accounts"` |
| `columns` | list of `Column` | 4 columns |
| `mysql_version_id` | int | `80410` |

`mysql_version_id` is kept because the proposal pins MySQL 8.4.x. If evidence turns out to be from another version the tool should warn rather than trust the output. (`80410` is how MySQL writes 8.4.10.)

---

## 2. Column

Part of `Schema`. One per visible column.

| Field | Type | Example |
|---|---|---|
| `name` | str | `"balance"` |
| `position` | int | `3` |
| `data_type` | str | `"int"` |
| `is_nullable` | bool | `True` |
| `is_primary_key` | bool | `False` |

`position` is the important one. `mysqlbinlog` only refers to columns by number (`@1`, `@2`, `@3`, `@4`), so we need something to turn those numbers into real column names.

The catch is that this number is **not** the `ordinal_position` from the raw `ibd2sdi` JSON. InnoDB adds its own hidden columns (`DB_TRX_ID`, `DB_ROLL_PTR`) and they show up in the JSON as well. In the SDI output a column has `hidden == 1` if it is a real user column and `hidden == 2` if it is internal. Only the `hidden == 1` ones get counted by `mysqlbinlog`.

In the test evidence, `ibd2sdi` reports 6 columns for `accounts.ibd` but only 4 of them are real:

| SDI ordinal | hidden | our `position` | name |
|---|---|---|---|
| 1 | 1 | 1 | account_id |
| 2 | 1 | 2 | owner |
| 3 | 1 | 3 | balance |
| 4 | 1 | 4 | status |
| 5 | 2 | - | DB_TRX_ID |
| 6 | 2 | - | DB_ROLL_PTR |

Here the two numbers happen to be the same because the hidden columns are at the end, but we should not depend on that. If a table has no primary key InnoDB adds a hidden `DB_ROW_ID` column and then the numbering shifts. If we get this wrong we would print one column's value under a different column's name, which in a forensic report means attributing evidence to the wrong field.

---

## 3. PhysicalRecord

From the `ibd2sql` adapter. One row as it exists in the `.ibd` file right now.

| Field | Type | Example |
|---|---|---|
| `database` | str | `"finance"` |
| `table` | str | `"accounts"` |
| `values` | dict | `{"account_id": 102, "owner": "Nimal", "balance": 7500, "status": "active"}` |
| `is_deleted` | bool | `True` |
| `page_no` | int | `4` |
| `page_offset` | int | `170` |

`is_deleted` is `True` for rows that only come back when you run `ibd2sql --delete only`.

`page_no` and `page_offset` say exactly where in the file the row was found, so anything we report can be checked against the raw bytes with a hex editor. `page_offset` is counted from the start of that page, not from the start of the file - that is how InnoDB itself addresses records. With the default 16 KB page size the absolute position is `page_no * 16384 + page_offset`. Row 102 sits at page 4, offset 170, which is `0x0100aa` in the whole file, confirmed against the raw bytes.

Note for implementation: `ibd2sql` does **not** report the page number or offset - its option list was checked. So the adapter has to read the `.ibd` page itself to fill these two fields. That is extra work but it is the same page-walking we would need anyway if we ever want more than what `ibd2sql` prints.

This was verified on the test evidence. Row 102 (`Nimal`) was inserted, deleted, and the `.ibd` exported. `SELECT` in MySQL does not show it any more and normal `ibd2sql` does not show it either, but `--delete only` brought the whole row back. The reason is that InnoDB does not actually erase a deleted row - it just sets a delete flag in the record header (bit `0x20`) and unlinks the record from the page's linked list. The bytes stay there until purge cleans them up. In the exported file the record header byte for row 102 is `0x20`, while rows 101 and 103 are `0x00`.

A deleted row is still a physical record, so a flag is used rather than a separate model.

One important limitation: this only works if purge has not run yet and nothing has reused the space. So the tool must say "no deleted records found", not "no records were deleted". Those mean different things and only the first one is safe to claim.

---

## 4. BinlogEvent

From the `mysqlbinlog` adapter. One row change.

| Field | Type | Example |
|---|---|---|
| `event_type` | str | `"DELETE"` |
| `database` | str | `"finance"` |
| `table` | str | `"accounts"` |
| `before` | dict or None | `{"account_id": 102, "owner": "Nimal", "balance": 7500, "status": "active"}` |
| `after` | dict or None | `None` |
| `timestamp` | datetime (UTC) | `2026-08-15 19:06:25+00:00` |
| `raw_timestamp` | str | `"260816  0:36:25"` |
| `gtid` | str or None | `"cb4d5c8e-9325-11f1-9975-00155dc1157f:10"` |
| `thread_id` | int or None | `13` |
| `log_position` | int | `1112` |
| `source_file` | str | `"mysql-bin.000006"` |

`event_type` is `"INSERT"`, `"UPDATE"` or `"DELETE"`, always uppercase.

`before` and `after` use `None` to mean the image does not exist at all, which is not the same as a column being NULL:

| Event | before | after |
|---|---|---|
| INSERT | `None` | new row |
| UPDATE | old row | new row |
| DELETE | old row | `None` |

Both dicts use real column names, not `@N`. Converting the positions is the adapter's job so nothing after it has to deal with them.

The timestamp needs care. `mysqlbinlog` prints the time in the server's local timezone and does not put any timezone marker on it. Our server is `+0530`, so the DELETE that printed as `260816 0:36:25` is really `2026-08-15 19:06:25` UTC. If we stored what was printed, then the moment we get evidence from a server in another timezone our event ordering would quietly be wrong, and ordering events is the main thing this tool does. Timestamps are therefore converted to UTC, with the original text kept in `raw_timestamp` so the report can show exactly what the tool printed.

`log_position` is the `end_log_pos` of the row event. It is only unique inside one binlog file (positions start again at 4 in each new file), so it always has to be used together with `source_file`.

---

## 5. TransactionMarker

Also from the `mysqlbinlog` adapter. Says which events were committed together.

| Field | Type | Example |
|---|---|---|
| `gtid` | str or None | `"cb4d5c8e-9325-11f1-9975-00155dc1157f:10"` |
| `xid` | int or None | `15` |
| `thread_id` | int or None | `13` |
| `status` | str | `"committed"` |
| `start_position` | int | `985` |
| `end_position` | int | `1143` |
| `source_file` | str | `"mysql-bin.000006"` |
| `event_positions` | list of int | `[1112]` |

`status` is `"committed"`, `"rolled_back"` or `"incomplete"`. Incomplete means the transaction started but there is no COMMIT or ROLLBACK for it, for example if the binlog file we were given just ends in the middle. That is actually evidence of a gap so we should not throw it away.

`event_positions` links back to `BinlogEvent.log_position`, and again only makes sense together with `source_file`.

`gtid` and `xid` are both optional because a server can run with GTID turned off. The adapter records whatever is actually there and does not guess the rest.

The adapter only records the markers it can see. Working out what the grouping means is the domain layer's job (Yasiru's `TransactionGroupingService`), not mine.

---

## 6. IntegrityResult

From the `innochecksum` adapter. The physical condition of one `.ibd` file.

| Field | Type | Example |
|---|---|---|
| `total_pages` | int | `7` |
| `damaged_pages` | int | `0` |
| `status` | str | `"valid"` |
| `page_counts` | dict | `{"Index page": 1, "SDI Index page": 1, "Undo log page": 0, ...}` |
| `raw_summary` | str | the tool's own output |

`status` is `"valid"`, `"damaged"` or `"unknown"`.

Worth noting: when every page is fine, `innochecksum` prints nothing at all and exits 0. So silence means success, not a parsing failure, and the adapter has to turn that empty output into an explicit `"valid"` result.

`page_counts` keeps the whole page-type breakdown from `innochecksum -S`, including the types that are zero. That may look pointless, but in the first test evidence set `Undo log page` is `0`, and that zero is exactly why the original balance of 5000 cannot be recovered from the `.ibd` at all - the undo history had already been purged. Dropping the zeros would throw away an important finding.

---

## 7. ProvenanceReference

Where a piece of information came from.

| Field | Type | Example |
|---|---|---|
| `evidence_id` | str | `"ev_b7785a0c"` |
| `tool_name` | str | `"mysqlbinlog"` |
| `tool_run_id` | str | `"run_3f21c8de"` |
| `source_file` | str | `"mysql-bin.000006"` |
| `log_position` | int or None | `1112` |

In forensics it is not enough to say "the balance is 4000". We have to be able to answer "how do you know that?" for every value we show. This model is what makes that possible.

A provenance field is not placed inside every other model because it would be repeated everywhere. Instead the repositories save the `tool_run_id` on each row, so the link is still there.

TODO: agree with Nisal on exactly what a tool run record stores. It needs at least the tool version, the full command, the exit code and a hash of the raw output, otherwise the run is not reproducible.

---

## 8. Warning

Something an adapter could not handle.

| Field | Type | Example |
|---|---|---|
| `code` | str | `"UNSUPPORTED_DATA_TYPE"` |
| `message` | str | `"Column 'photo' has type BLOB which is not supported"` |
| `context` | dict | `{"table": "accounts", "column": "photo"}` |

Codes expected to be needed:

| Code | When |
|---|---|
| `UNSUPPORTED_DATA_TYPE` | a column type the adapter cannot decode |
| `PARTIAL_ROW_IMAGE` | the binlog row image is not FULL so some columns are missing |
| `UNVALIDATED_MYSQL_VERSION` | evidence is not from a MySQL 8.4.x server |
| `SCHEMA_NOT_FOUND` | a binlog event mentions a table we have no schema for |

This is a model and not just a log line because warnings have to end up in the final report. If an adapter quietly skipped a column the investigator needs to know, because it changes how much they can trust the conclusion.

---

## 9. UndecodableValue

Used inside `values`, `before` and `after` when the adapter could read that a column exists but could not turn its bytes into a real value.

| Field | Type | Example |
|---|---|---|
| `reason` | str | `"BLOB type not supported"` |

So a row with one bad column looks like this:

```
{"account_id": 102, "owner": "Nimal", "photo": UndecodableValue("BLOB type not supported")}
```

The team decided we need a separate marker for this instead of just putting `None`. The reason is that `None` already means a real SQL NULL, and "the database stored NULL here" and "we could not read this" are completely different facts. Mixing them up would let the tool report a NULL that was never in the database, which is exactly the kind of mistake that would destroy the report's credibility.

When this gets saved to SQLite as JSON it needs a shape that cannot collide with real data, something like `{"__undecodable__": "BLOB type not supported"}`. TODO: confirm this with Nisal since he owns the storage side of the pipeline.

Every `UndecodableValue` should also produce a `Warning`, so it shows up in the report and not only inside a row.

---

## 10. BinlogInventory

Built from `mysql-bin.index`, which is the file MySQL uses to keep track of its own binary logs. One inventory per evidence set.

| Field | Type | Example |
|---|---|---|
| `index_file` | str | `"mysql-bin.index"` |
| `listed_files` | list of str | `["mysql-bin.000001", ..., "mysql-bin.000006"]` |
| `present_files` | list of str | `["mysql-bin.000001", ..., "mysql-bin.000006"]` |
| `missing_files` | list of str | `[]` |

This is how we notice that a binlog file is missing. Without it we would have some number of files and no way of knowing whether that is all of them. With it we can say "the server had 6 logs and we were given 5", which feeds straight into the "Unresolved" reconciliation result - the case where our reconstructed state does not match the `.ibd` but a missing log could explain the difference. That is the difference between reporting a gap and wrongly reporting tampering.

Worth noting: the index file stores **absolute paths**, like `/var/log/mysql/mysql-bin.000006`, but our working copies sit in the case folder. So the comparison has to be done on file names only, not full paths, otherwise every single file would look missing.

---

## Design decisions

**1. Row values are a dict of column name to value, not a list.** The whole reason we normalize is to get away from positional `@N` numbering, and a list would bring that straight back. Everything downstream would need the schema again just to know what index 2 means.

**2. Timestamps are converted to UTC, and the original text is kept too.** Putting events in the right order is the main job of the tool, and `mysqlbinlog` prints local time with no timezone on it. Keeping the raw text as well means a report can still show what the tool actually printed.

**3. A deleted row is a flag on `PhysicalRecord`, not a separate model.** A deleted row is still a row on the page, and InnoDB itself represents deletion as a single flag bit, so a boolean matches what is really happening.

**4. Provenance is its own model instead of a field on everything else.** Keeps the models small. The link is not lost because the SQLite tables store `tool_run_id` on every row.

**5. `PhysicalRecord` stores the page number and offset where the row was found.** Agreed with the team. It means anything we report can be checked against the raw bytes, which matters for a forensic tool. The cost is that the adapter has to walk the `.ibd` page itself because `ibd2sql` does not give us this.

**6. An undecodable value gets its own marker, not `None`.** Agreed with the team. `None` already means a real SQL NULL, and reporting "the value was NULL" when we actually mean "we could not read it" would be a false statement about the evidence.

**7. We model the binlog file list from `mysql-bin.index`.** Agreed with the team. It is the only way to tell that a log file is missing, and that difference decides whether a mismatch is reported as an evidence gap or wrongly reported as tampering.

---
