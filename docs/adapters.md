# FactumDB Tool Adapters

The adapters are the layer between the four forensic tools and the rest of FactumDB. Each one runs its tool on a verified working copy of the evidence, reads what the tool prints, and turns it into the shapes in `canonical-model.md`. After that point nothing in FactumDB reads raw tool output again: the domain services and the UI only see the canonical model, through the case database in `sqlite-schema.md`.

This document covers what each adapter runs and reads and why, how normalization narrows the stored evidence for the analysis, how every stored value keeps its provenance, and what the adapters cannot do. The adapters are in `backend/adapters/tools/`, and normalization and storage in `backend/adapters/persistence/`.

## The adapters at a glance

| Adapter | File | Runs | Reads | Produces |
|---|---|---|---|---|
| `InnochecksumAdapter` | `innochecksum_adapter.py` | `innochecksum <file>`, then `innochecksum -S <file>` | `.ibd` | `IntegrityResult` |
| `Ibd2SdiAdapter` | `ibd2sdi_adapter.py` | `ibd2sdi <file>` | `.ibd` | `Schema` |
| `Ibd2SqlAdapter` | `ibd2sql_adapter.py` | `<python> main.py <file> --sql --complete-insert`, and the same again with `--delete only` | `.ibd` | `PhysicalRecord`s |
| `MysqlBinlogAdapter` | `mysqlbinlog_adapter.py` | `mysqlbinlog -v -v --base64-output=DECODE-ROWS <file>` | one binlog | `BinlogEvent`s, `TransactionMarker`s and warnings |
| `MysqlBinlogIndexAdapter` | `binlog_index.py` | no tool, the file is read directly | `mysql-bin.index` | the log names the server listed |

The pipeline uses them in this order: validate the pages, extract the schema, extract the page rows, then decode the binlogs. The schema has to come before the binlogs, because `mysqlbinlog` only numbers the columns and the schema is what names them. The index is read at the start of the binlog stage.

## Rules every adapter follows

- **Only a verified working copy is read.** A tool run is refused unless the evidence file has been copied and the copy's hash matches the original's (`ToolRunAuditService.start`). The original file is never given to a tool.
- **Nothing is written to the evidence.** `innochecksum` can rewrite checksums with `-w`, and that option is never used.
- **A failed tool is an error, not an empty result.** Each adapter raises an error with the exit code and the start of the tool's error output. Treating a failure as "no rows" would turn a broken run into a finding.
- **Nothing is guessed.** A value that cannot be put under the right column is left out, and a value that cannot be read becomes an `UndecodableValue`, never `None`, because `None` means a real SQL NULL.
- **Reading is kept apart from running.** Each adapter has a `parse()` that takes the tool's output as text, so the tests use saved output and do not need MySQL.

---

## 1. innochecksum: page validation

`innochecksum` checks the checksum of every page in an `.ibd` file. The adapter runs it twice: once with no options to check the pages, and once with `-S` to count each type of page.

Three things about this tool decide how its output is read:

- **Silence means success.** When every page is fine, `innochecksum` prints nothing and exits 0. The adapter turns that into an explicit `valid` result instead of mistaking it for missing output.
- **Exit code 1 has two meanings.** The tool exits 1 when it finds a damaged page, and also when it could not check the file at all: a missing file, a file it could not lock, a file too small to be a tablespace. Only the first is damage. A bad page is reported on a line starting `Fail` and a failed run on a line starting `Error`, so the adapter counts the `Fail` lines. A non-zero exit with no `Fail` line is raised as an error, not reported as damage the evidence does not show.
- **Zero counts are kept.** The `-S` summary lists every page type, including those with a count of 0. In the scenario 1 evidence `Undo log page` is 0: the file holds no undo records, so an old value that only the undo log kept cannot come from it (limitation 2). Dropping zeros as noise would lose that.

The status is decided in this order: the check run found a bad page → `damaged`; the summary could not be read → `unknown`; otherwise `valid`. Damage comes first, because a file the tool has already called invalid must not be reported as only "unknown". `total_pages` is the sum of the page counts, which saves a third run of the tool.

The integrity result is stored against the `-S` run, and the check run before it is recorded in `tool_runs` too. When a damaged page is found the tool exits 1, so its run is recorded as failed. Saving accepts a failed run for `innochecksum` only, because damage is the most important result this stage can give.

---

## 2. ibd2sdi: the table definition

`ibd2sdi` prints the data dictionary that InnoDB keeps inside the `.ibd` file itself, as JSON. The adapter takes the `Table` object from it and builds a `Schema`: the database, the table, its columns and the MySQL version (`mysql_version_id`, for example `80411` for 8.4.11).

The main job here is the column positions. `mysqlbinlog` only refers to columns by number, `@1`, `@2`, ..., and it counts visible columns only. The dictionary also lists InnoDB's hidden system columns (`DB_TRX_ID`, `DB_ROLL_PTR`, and `DB_ROW_ID` when the table has no primary key), so the adapter keeps only the columns with `hidden == 1`, sorts them by `ordinal_position` and numbers them again from 1. Getting this wrong would put one column's value under another column's name. Section 2 of `canonical-model.md` has the worked example.

The primary key comes from the `PRIMARY` index. That index lists every column stored in the clustered index, so only its elements with `hidden == false` are key columns, and they point at columns by their place in the unfiltered list (`column_opx`). That is why each column's original place is kept until the key has been worked out.

`data_type` is the full declared type, such as `decimal(12,2)` or `enum('pending','paid','refunded')`. The binlog adapter needs the ENUM labels from it, and the domain engine reduces it to the base type (`decimal`, `enum`) when it checks which types it supports.

---

## 3. ibd2sql: rows on the page

`ibd2sql` reads rows straight out of the `.ibd` file and prints them as `INSERT` statements. Run normally, it prints the live rows. Run with `--delete only`, it prints rows that are deleted but still on the page: InnoDB only sets a delete flag in the record header, and the bytes stay until purge reclaims the space.

`ibd2sql` is a Python script, not an installed program. FactumDB uses v2.4 (commit `e6e8c380`, the revision both desktop bundles pin). Its path comes from `FACTUMDB_IBD2SQL_PATH` or the desktop Settings, and a Python interpreter runs it; the desktop app uses its own.

- **`--complete-insert` is always passed**, so every statement carries the column names:

  ```
  INSERT INTO `finance`.`accounts`(`account_id`,`owner`,`balance`,`status`) VALUES (102,'Nimal',7500,'active');
  ```

  The adapter reads the names the tool gives instead of assuming the values are in schema order.
- **Values are split on commas outside quotes only.** A plain split would cut an owner like `Perera, A.` in two.
- **Either quote can open a string, and only that quote closes it.** `ibd2sql` normally uses single quotes, but switches to double quotes when the value contains an apostrophe: `(104,"Perera, A. O'Brien",9000,'active')`. Both ways of escaping a quote, doubling it and a backslash, are handled. This was found by exporting a real row: the synthetic tests all used single quotes and had passed.
- **Numbers keep their exact value.** Whole numbers become `int`, and decimals such as `4000.10` become `Decimal`, never `float`, which cannot hold 4000.10 exactly.
- **Binary values are not decoded.** A value printed as `0x...` (`BLOB`, `BINARY`, `VARBINARY`) becomes `UndecodableValue("binary data is not decoded")`.
- **Anything else is kept exactly as printed**, such as dates, times and text.
- **A row that does not split cleanly is not stored.** If the number of values differs from the number of column names, pairing them up could put a value under the wrong column, so the row is skipped. Before the quote fix above, this guard is what dropped the `O'Brien` row instead of storing it with its values in the wrong columns.

Live and deleted rows come from two separate runs, and each row is stored against the run that produced it. The second run only happens when **Include deleted physical rows** is ticked in the desktop Settings, which is off by default.

`page_no` and `page_offset` are always empty, because `ibd2sql` does not say where it found a row (limitation 1).

---

## 4. mysqlbinlog: row changes and transactions

With `-v -v --base64-output=DECODE-ROWS`, `mysqlbinlog` prints every row change as comment lines. This is the balance update from scenario 1:

```
#261013 12:02:24 server id 1  end_log_pos 1492 CRC32 0x44dc6ec6   Update_rows: table id 111 flags: STMT_END_F
### UPDATE `finance`.`accounts`
### WHERE
###   @1=101 /* INT meta=0 nullable=0 is_null=0 */
###   @2='Amal' /* VARSTRING(400) meta=400 nullable=1 is_null=0 */
###   @3=5000 /* INT meta=0 nullable=1 is_null=0 */
###   @4='active' /* VARSTRING(80) meta=80 nullable=1 is_null=0 */
### SET
###   @1=101 /* INT meta=0 nullable=0 is_null=0 */
###   @2='Amal' /* VARSTRING(400) meta=400 nullable=1 is_null=0 */
###   @3=4000 /* INT meta=0 nullable=1 is_null=0 */
###   @4='active' /* VARSTRING(80) meta=80 nullable=1 is_null=0 */
```

The adapter reads this line by line and remembers where it is: the event header (time and `end_log_pos`), `SET @@SESSION.GTID_NEXT` (the transaction's GTID), `thread_id`, `Table_map` (which table a table id means), `Write_rows`, `Update_rows` and `Delete_rows` (the start of a row event), the `###` lines (the before and after images), and `BEGIN`, `Xid`, `COMMIT` and `ROLLBACK` (where a transaction starts and ends).

**Naming the columns.** The decoder is built for one case and looks up each table's schema in that case only. `@N` becomes the name of the column at position N. If the case has no schema for the table, the row is not stored and a `SCHEMA_NOT_FOUND` warning is recorded. If a number has no column, that one value is left out with a `COLUMN_POSITION_UNKNOWN` warning. These are the only two warnings the adapters raise.

**`None` is not NULL.** An `INSERT` has no before image and a `DELETE` has no after image, so those are `None`. A column that was NULL is a value inside an image.

**Times.** The header prints the server's local time with no zone (`#261013 12:02:24`). The zone is not guessed: `mysqlbinlog` prints it in the commit timestamp comment, `original_commit_timestamp=1791873144328337 (2026-10-13 12:02:24.328337 +0530)`, so the adapter reads the offset from there and converts every event time to UTC, here `2026-10-13 06:32:24`. The text as printed is kept in `raw_timestamp`. A time seen before any offset is read as UTC, but MySQL 8 prints the offset before the first row event.

**One event, several rows.** A statement that changes several rows can be logged as one event holding several row images, all at the same `end_log_pos`. Each row gets a `row_index` (0, 1, ...) so the rows stay separate, and the transaction marker lists the position once, because it lists events, not rows.

**Transactions.** `BEGIN` opens one. `Xid` or `COMMIT` closes it as `committed`, and `ROLLBACK` as `rolled_back`; a `ROLLBACK` that `mysqlbinlog` adds to its own output (marked `added by mysqlbinlog`) is ignored. If the file ends inside a transaction, it is recorded as `incomplete`, because that is a real gap in the evidence.

**Values written the way ibd2sql writes them.** The analysis compares the two tools value by value, so the binlog values are converted to match the page side (decision 8 in `canonical-model.md`): an ENUM's position becomes its label, a `DATE` printed with colons gets dashes, a `TIMESTAMP` in seconds since 1970 becomes the wall-clock time in the zone of the machine running the analysis (as `ibd2sql` does), and binary values become `UndecodableValue`. A value in a form the parser does not know is also marked undecodable, rather than kept as text that would look like real data.

**Partial row images.** With `binlog_row_image=MINIMAL`, the before image holds only the key and the after image only the changed columns. The adapter stores what was logged and does not fill in the rest; the domain engine treats the missing columns as not observed.

**Table creations.** The adapter also notes every `CREATE TABLE` it sees, with its file and position (`TableCreation`, stored in `table_creations`). Yasiru added this for the presence comparisons. `CREATE TABLE IF NOT EXISTS` is skipped, because it does not prove the table was created at that point.

**File names.** The adapter reads a working copy named `<evidence id>-mysql-bin.000006`, but its events are stored under the name the log was registered with, `mysql-bin.000006`. That is the name in `mysql-bin.index`, and the analysis orders the logs by it.

---

## 5. mysql-bin.index: which logs the server had

No tool is involved here. The index is a text file MySQL writes itself: one log path per line, oldest first. The paths are where the logs were on the server (`/var/log/mysql/mysql-bin.000001`, `./mysql-bin.000001` when the logs are in the data directory, or `C:\ProgramData\MySQL\Data\mysql-bin.000001` from a Windows server), not where our working copies are, so only the file names are kept. Both `/` and `\` count as separators, whichever system FactumDB runs on: an index from a Windows server read on Linux would otherwise keep its whole paths, and every log would look missing. A name listed twice is refused: MySQL never writes one, so the file was edited or damaged, and the order of the logs, which the transaction grouping relies on, can no longer be trusted.

The binlog stage reads the index before it decodes any log, and stores an inventory: the logs the index lists, the binlogs registered in the case, and the listed ones that are missing. A missing log is then reported as an evidence gap instead of going unnoticed. If no index was registered, binlog coverage is reported as unknown (R-COV-001), never as complete.

There is no tool run behind an inventory. The index is registered evidence with its own hash, and that is what ties the inventory to the file it was read from.

---

## 6. Normalization

By the time the evidence is stored, the adapters have done most of what normalization means: columns have names, times are in UTC, every changed row is one event, and both tools write a value the same way. What is left works on the whole case. `SqliteEvidenceNormalizer` gathers everything stored for the case and applies the investigator's scope, the databases and tables the analysis should cover (`case_scopes` in `sqlite-schema.md`).

- The scope is applied the same way to schemas, page rows and binlog events. Filtering a table's rows but not its events would make the domain engine report a missing tablespace that is in fact there.
- A transaction that changed tables inside and outside the scope keeps only its in-scope events. One with no in-scope events is left out, and one that listed no events at all is kept, because nothing in it says which tables it was about.
- Only the case's own evidence files are read, so another case in the same database file never becomes part of this one (decision G in `sqlite-schema.md`).
- The scope filters what the analysis looks at, never what is stored. Nothing is thrown away at extraction (for example with `mysqlbinlog --database`), so a narrow scope can be widened later without extracting anything again.

The normalization stage records the scope it used and, for each kind of evidence, how much was in scope out of how much is stored (`normalizations`). When the analysis asks for its input, the domain repository applies that same scope again and compares the counts. If the evidence changed in between, for example a binlog decoded again, the analysis is refused until the case is normalized again.

---

## 7. Provenance: from a value back to a command

Every value FactumDB shows has to answer "how do you know that?". The adapters do this together with the audit service and the case database:

1. **Before a tool runs**, `AuditedSubprocessRunner` (`adapters/tools/audit.py`) asks the audit service (`ToolRunAuditService`, in Nisal's application layer) to start a tool run. The service checks that the evidence is verified and records a `running` tool run: the tool's name and version, the executable's path and SHA-256, and the arguments as a JSON array. For `ibd2sql` the executable recorded is `main.py`, not the Python interpreter, because the script is what produced the rows.
2. **After it runs**, the exit code and status are recorded, and the exact bytes of stdout and stderr are saved to `raw-output/<tool run id>/stdout.bin` and `stderr.bin` in the case folder, with their SHA-256 and size in the tool run.
3. **The version** is read from the tool itself with `--version` the first time each tool is used (`versions.py`), not written in configuration, because an ordinary system update can change it without anything in the project changing. Reading it is not done to the evidence, so it is not recorded as a run. The MySQL tools give `8.4.11`, and `ibd2sql` gives `ibd2sql v2.4-20260921`.
4. **Each result comes back with its run.** The bridges in `extraction.py` return each result together with the ids of the tool runs behind it. `ibd2sql`'s live rows and deleted rows each keep their own run.
5. **Saving checks the link.** Before anything is stored, `SqliteExtractionRepository` checks that the tool run belongs to the same case and evidence file, comes from the right tool (a schema cannot point at an `innochecksum` run), and succeeded, apart from `innochecksum` finding damage (section 1).
6. **Every stored row keeps it.** Each extracted row has an `evidence_id` and a `tool_run_id` (decision E in `sqlite-schema.md`). When rows are read for the analysis, a `ProvenanceReference` is rebuilt from them (`_provenance.py`), and the domain engine copies it into its findings. One row change can be traced to its run from `(source_file, log_position, row_index)` (`provenance_for`).

So for any value in a report:

| Question | Where the answer is |
|---|---|
| Which file was it read from? | `evidence_files`: the original's path and SHA-256, and the working copy's |
| Which command produced it? | `tool_runs`: the executable and its SHA-256, the arguments, the version |
| What exactly did the tool print? | `stdout.bin` and `stderr.bin`, which can be checked against the hashes in `tool_runs` |
| Where in the file? | For a row change: the binlog's name, the position and the row index. For a page row: only the `.ibd` file (limitation 1) |

---

## 8. Limitations

Each of these was checked against the code.

**1. A page row has no page location.** `page_no` and `page_offset` are always empty. `ibd2sql` does not report where it found a row, and FactumDB has no page reader of its own, so decision 5 in `canonical-model.md` was not built. A row's place can still be found by hand: in the scenario 2 evidence the deleted account 102 starts at page 4, offset 170.

**2. Deleted rows are only found until purge.** `--delete only` returns delete-marked records still on the page. Once purge removes them or the space is reused they are gone, so the tool can say "no deleted rows found", never "no rows were deleted". Old values are found the same way: an update that rewrites a row may leave the old version on the page (scenario 4 has some), but an update made in place leaves the old value only in the undo log, which MySQL keeps in its own undo tablespaces, not in the table's `.ibd`. That is why scenario 1's original balance of 5000 is only in the binlog. In the desktop app, deleted rows are only extracted when **Include deleted physical rows** is ticked.

**3. Binary values are not decoded.** `BLOB`, `BINARY` and `VARBINARY` values become `UndecodableValue` on both sides, and no warning is raised for them; the reconciliation shows them as Unsupported. Which types are compared at all is decided by the domain engine (`DEFAULT_SUPPORTED_TYPES`), and `JSON` is not one of them.

**4. Only row-based logging is read.** With `binlog_format=STATEMENT`, or a statement logged as SQL under `MIXED`, the change is written as SQL text, which the adapter does not parse. The transaction is still recorded, but with no row events and no warning.

**5. Partial row images stay partial.** With `binlog_row_image=MINIMAL` only the key and the changed columns are logged. Nothing fills in the rest, so an agreeing value can be weaker than Exact. The `PARTIAL_ROW_IMAGE` warning planned in `canonical-model.md` was not built.

**6. One table definition for every event.** Columns are named with the definition in the `.ibd` as it was acquired. If a column was added, dropped or moved after an event was logged, that event's `@N` numbers may belong to other columns. The adapter only notices when a number has no column at all (`COLUMN_POSITION_UNKNOWN`).

**7. Events need the table's tablespace.** A row event for a table whose `.ibd` is not in the case cannot have its columns named, so it is not stored, only warned about (`SCHEMA_NOT_FOUND`). Scenario 4 has one such event.

**8. The MySQL version is recorded, not checked.** `mysql_version_id` is stored and exported, but evidence from another MySQL version is not warned about. The `UNVALIDATED_MYSQL_VERSION` warning was planned but not built.

**9. `TIMESTAMP` values depend on the machine.** Both sides are shown in the time zone of the machine running the analysis, so they agree with each other on any machine, but the text differs from one machine to another. Event times are in UTC and are not affected.

**10. A row that does not split cleanly is dropped without a warning.** The guard in section 3 stops a wrong value being stored, but the skipped row is not counted or reported. It has not happened on any of the four datasets since the quote fix.

**11. Output is read as UTF-8.** Tool output is decoded as UTF-8, and any bytes that are not valid UTF-8 are replaced without a warning. Text stored in another character set may not come through exactly. The datasets use MySQL 8.4's default, `utf8mb4`.

**12. The tools are trusted.** Each run records the SHA-256 of the executable, so a changed tool can be noticed afterwards, but nothing checks the hash against a known-good value before the run.

**13. Tested with one set of versions.** The parsers read text, and the tools may print differently in other versions. They were developed and tested with the MySQL 8.4 utilities (8.4.10 and 8.4.11) and `ibd2sql` v2.4, and the desktop bundles ship MySQL 8.4.11 and the same `ibd2sql` revision.
