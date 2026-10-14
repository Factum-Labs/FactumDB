# FactumDB final evaluation: 500-row demonstration

Use this dataset for the five-minute practical demonstration, leaving the other
five minutes of your ten-minute slot for the presentation. All people, businesses
and activity are fictional. The database is named `demo_market`.

## What to import

Create a case named **Evaluation Demo - Market Investigation** in FactumDB.
Import **all five `.ibd` files** from `evidence_set/ibd/` and **all four files**
from `evidence_set/binlog/`: three numbered binary logs and `mysql-bin.index`.
Run **complete analysis**, with **deleted-row extraction disabled**.

Only these nine files are forensic input. Do not import the SQL, Markdown,
manifest or observed-results JSON. Do not import the ZIP directly: extract it
first. The index's original private-server paths are expected; the application
uses the filenames to establish the inventory.

The files are real MySQL 8.0.43 InnoDB tablespaces and ROW-format binary logs,
not renamed text. All acquired checksums validate, all three indexed logs are
present, and no files have been intentionally corrupted. SQL logging was briefly
disabled on the private generator server to create the controlled discrepancies.
The evidence totals **597,863 bytes**, approximately **584 KiB**.

| Table | Starting rows | Final live rows | Purpose |
|---|---:|---:|---|
| customers | 80 | 80 | Contact details |
| orders | 80 | 81 | Financial amounts, destinations and history |
| order_lines | 160 | 160 | Composite primary keys |
| payments | 160 | 158 | Logged and hidden deletion |
| staff | 20 | 20 | Application role changes |
| **Total** | **500** | **499** | |

Amounts are integers in minor units: `12000` means 120.00; `999999` means
9,999.99. The schema does not specify a currency. Initially each order has two
lines and two payments, both pairs summing to its total. Deliberate later
changes disrupt some of these relationships. There are no declared foreign-key
constraints; this is a small forensic fixture, not a production commerce schema.

## Verified result totals

The current backend completed all ten pipeline stages in **5.82 seconds** in the
recorded validation. Import, analysis and complete result retrieval together took
about seven seconds; use `evidence_set/OBSERVED_RESULTS.md` for the precise latest
measurement. This is a local backend measurement, not a promise about another
laptop or a timed GUI rehearsal. The validation uses the real extraction tools
and analysis backend, with the repository's test device-verification port for an
isolated examiner; GUI login and native device verification were not tested.

All **20 acceptance checks passed**. There are **499 live extracted rows**,
**509 decoded row changes**, **13 grouped committed transactions**, **no missing
logs**, and **no adapter warnings**.

| Record classification | Count | How to explain it |
|---|---:|---|
| Exact | 493 | All compared fields and presence agree under the applicable rules |
| Conflicting | 5 | At least one comparable value or presence disagrees |
| Strong | 2 | Agreement with a history or row-image limitation |
| Unresolved | 1 | Missing physical field values prevent a complete comparison |
| Partial | 0 | No record rolls up to this category in this fixture |
| Unsupported | 0 | No record rolls up to this category in this fixture |
| **Total reconciled identities** | **501** | Includes historical identities and the unlogged insertion |

There are **2,647 field/presence comparisons**: 2,615 Exact, 7 Conflicting,
11 Strong and 14 Unresolved. These are comparison counts, not additional records.
The 501 identities differ from the 499 live rows because both deleted payment
identities remain in the logs. Composite-key continuity merges the old and new
line keys rather than creating an extra unrelated record.

## All deliberately seeded results

The following expectations come from `baseline.sql` and `activity.sql`.
Observed classifications and every non-Exact comparison are separately recorded
in [OBSERVED_RESULTS.md](evidence_set/OBSERVED_RESULTS.md).

| Record | Controlled activity and values | Observed result | Demo priority |
|---|---|---|---|
| `orders:20` | Hidden amount `12000` -> `999999`; destination `LOCAL-100020` -> `EXT-441199`; status `settled` -> `waived` | **Conflicting** on these three fields | Main example |
| `customers:31` | Hidden email `customer031@example.invalid` -> `shadow@example.invalid` | **Conflicting** on email | Optional quick example |
| `staff:8` | Hidden application role `clerk` -> `administrator` | **Conflicting** on role | Optional quick example |
| `payments:25` | Hidden deletion; log expects a live payment for order 13, amount `5650`, channel `bank`; live page has no row | **Conflicting** presence; four field values **Unresolved** | Main example |
| `orders:900001` | Hidden insertion for customer 12, amount `4700000`, status `settled`, destination `EXT-441199`, note `Unlogged fabricated order` | **Conflicting** presence; six fields **Unresolved**, because no log-derived values exist | Main example |
| `orders:10` | Logged change from `LOCAL-100010` to `EXT-887711`; note first `Beneficiary changed`, then `Receipt verified` | **Exact** final comparison, with reconstructable changes | Main history example |
| `staff:7` | Role `clerk` -> `administrator` in the same logged transaction as order 10's destination change | **Exact** | Optional transaction example |
| `payments:30` | Logged deletion of payment for order 15, amount `5750`, channel `card` | Presence **Exact** (`absent` / `absent`); four fields **Unresolved**; record rollup **Unresolved** | Explain the limit if asked |
| Order 10, line 2 -> line 3 | Logged composite-key change `(10,2)` -> `(10,3)` | Identity continuity finding `R-CORR-010`; values agree | Optional advanced example |
| `orders:50` | Logged delete then insert under the same key; final values match original except note becomes `Replacement after cancellation` | **Exact**, with key-reuse finding `R-CORR-012` | Optional advanced example |
| `orders:60` | Logged MINIMAL-image update of note to `Supervisor reviewed`; other columns omitted from that update | Record **Strong**; five fields Strong; changed note and presence Exact | Optional limit example |
| `orders:71` | Hidden amount `17100` -> `777777`, then logged note update to `Receipt reissued`; that update's before-image already contains `777777` | Before-image mismatch `R-HIST-008`; six fields **Strong**, presence Exact; record Strong | Optional advanced example |
| `orders:40` | Attempted amount update `14000` -> `1`, then rollback | **Exact**, final amount `14000`; attempted write is not a durable binlog row event | Explain only if asked |
| Remaining identities | Ordinary fictional baseline data | **Exact** | Establish normal control behavior |

Order 71 demonstrates why a suspicious history can finish with agreeing values:
the later logged before-image exposes a missing transition and supplies the
changed amount. Do not promise a Conflicting amount for that record.

The logged payment deletion demonstrates a different distinction: agreement
that a row is absent does not supply an independent physical copy of its former
fields. The historical values are reconstructed from logs; they are not recovered
deleted page remnants with this setting.

## Recommended five-minute live script

Rehearse the exact clicks once on your presentation laptop. Sign in and open the
file folders before the timed slot. The names below match the current navigation:
**Transactions**, **Record history**, and **Reconciliation**.

### 0:00-0:25 - Introduce the evidence and case

Create the case, select the nine evidence files and say:

> "This is a controlled fictional marketplace dataset with 500 starting rows.
> I have acquired the InnoDB tablespaces and binary logs. FactumDB will compare
> the state reconstructed from logged changes with the state found in the pages."

### 0:25-0:55 - Run complete analysis

Keep deleted-row extraction off. Start analysis and show the completed stages:

> "The pipeline verifies evidence hashes and page integrity, extracts records,
> decodes the logs, groups transactions, reconstructs histories and reconciles
> the two evidence sources. These supplied logs have no detected inventory gap."

If analysis finishes quickly, move straight on. Do not spend time reading every
stage. If it runs beyond about 45 seconds, open the previously analysed backup
case prepared during rehearsal.

### 0:55-1:20 - Show the reconciliation overview

Show **Reconciliation** and say:

> "Most records agree. There are five conflicting records, two Strong records
> and one Unresolved record. These categories distinguish disagreement from
> evidence limitations. A conflict is a reason to investigate; it does not by
> itself identify an attacker."

### 1:20-2:10 - Explain the main financial discrepancy

Choose the **Conflicting** result filter, expand `orders:20`, and show the
`amount_minor`, `destination` and `status` comparisons:

> "For order 20, the logged amount is 12,000 minor units, or 120.00. The physical
> row contains 999,999 minor units, or 9,999.99. Its destination and status also
> differ. The application shows the conflicting values and the evidence
> references used for the comparison. In this controlled fixture, I created
> those differences using unlogged writes."

Open one comparison's provenance if time permits. Do not spend time on every
ordinary matching field.

### 2:10-2:55 - Show deletion and insertion

Remain in the Conflicting filter. Expand `payments:25`, then `orders:900001`:

> "Payment 25 is present in the reconstructed log state but absent from the
> live page snapshot. Order 900001 is the reverse: it is present in the pages
> without a corresponding logged insertion in this acquired history. These
> are presence conflicts. Where one source has no field value, the tool marks
> that individual field Unresolved rather than inventing a value."

### 2:55-3:45 - Demonstrate a reconstructed history

Clear the filter, expand `orders:10` and use **Open record history**. Show its
logged destination and note changes, followed by the physical state:

> "Order 10 has a sequence of logged changes. We can follow the destination
> change and the later receipt note, then compare the final reconstructed state
> with the physical row. This record is Exact because they agree. Exact means
> consistency under the rules; it does not mean the change was authorized."

If useful, briefly show **Transactions**: order 10's first update and staff 7's
role change share a committed transaction. Avoid scrolling through all 13 groups.

### 3:45-4:15 - Explain confidence limits

Show the **Strong** filter and `orders:60`, or refer to the summary:

> "A partial row image does not repeat every column. The tool retains the
> observed change and marks the appropriate comparisons Strong. It separates
> these limitations from positive conflicts."

If asked about the Unresolved record, show `payments:30` and explain that both
sources agree on absence while its former fields lack a physical counterpart.

### 4:15-4:35 - Show the report

Open the report preview or a report saved during rehearsal:

> "The summary PDF presents the findings and limitations. The full JSON retains
> the detailed analysis and evidence references for further review."

Report generation time was not included in the pipeline benchmark above.
Prepare the preview during rehearsal if export rendering is slow on the laptop.

### 4:35-5:00 - Buffer or one question

Finish with:

> "This demonstration shows evidence integrity checks, reconstructable history,
> and reconciliation that distinguishes agreement, disagreement and uncertainty."

Skip the advanced examples if time is tight. Order 20, the two presence
conflicts and order 10's history are the essential demonstration.

## Likely evaluation questions

**Why 500 records?** "It provides normal background records and several
controlled findings while leaving time to inspect the evidence. Larger-scale
performance testing is a separate exercise."

**Why 501 analysed records but 499 physical rows?** "Two payment identities
remain in the logs after deletion. Analysis includes those historical identities,
not just currently live rows."

**Do valid hashes prove there was no tampering?** "They establish that the
acquired files match the recorded hashes. Valid page checksums establish the
tested structural integrity. Neither proves that earlier database writes were
authorized; logically inconsistent but structurally valid evidence can remain."

**Does a complete binlog index prove every action was logged?** "It shows no
listed file is missing in this acquisition. Writes with logging disabled can
still be absent, which is what the controlled hidden-write examples exercise."

**Is the staff role a MySQL administrator privilege?** "No. It is an application
data field. These inputs do not establish MySQL server GRANT privileges."

**Did you recover a deleted row from disk?** "With deleted-row extraction off,
the demonstration reconstructs deleted record history from binlogs and compares
presence with live page extraction. Deleted page remnants depend on purge and
are outside this reproducible baseline."

**Can it prove SQL injection or identify the attacker?** "These row files show
data changes and inconsistencies. Attribution, the entry point and authorization
require supporting application, access or host evidence."

## Prepare before evaluation

1. Extract `demo-evidence.zip` if using the portable copy. Keep the guide outside
   the import selection.
2. Open FactumDB and confirm that its extraction tools are available. Sign in
   using your normal examiner account.
3. Run this dataset once with deleted-row extraction off. Confirm the totals
   above and save this analysed case as **Demo Backup - Already Analysed**.
   The isolated backend validation case is not automatically added to your
   normal app workspace.
4. Prepare its PDF preview/export and a screenshot of order 20's comparison.
5. Create a new case for the live run; keep the backup case available.
6. Rehearse navigating the Conflicting filter and opening order 10's history.
   Allow for your own explanation and clicks, not just processing time.

## Reproduce and verify

From the repository root in PowerShell:

```powershell
# A new isolated MySQL 8.0 server; never connects to your existing database.
# Existing output is refused, so use a fresh directory for regeneration.
py -3.11 datasets/demo_500/generate.py --mysql-bin 'C:/Program Files/MySQL/MySQL Server 8.0/bin' --output datasets/demo_500/evidence_recreated

# Validates hashes and real backend results using an isolated test examiner.
py -3.11 datasets/demo_500/validate.py --mysql-bin 'C:/Program Files/MySQL/MySQL Server 8.0/bin' --ibd2sql src-tauri/resources/runtime/windows/ibd2sql/main.py
```

For a regenerated directory, add `--evidence datasets/demo_500/evidence_recreated`
to the validation command. File hashes and event timestamps change on regeneration;
the logical activity and expected findings remain the same. Re-run validation for
the new acquisition instead of reusing the old manifest.

Generated `.ibd` files, binlogs, the portable ZIP, private server scratch files
and isolated validation cases stay local and are ignored by Git. Keep a separate
copy of the ZIP for the evaluation machine; a normal Git clone does not contain
the binary evidence. The `.ibd` files support offline forensic extraction and are
not a complete restorable server backup.

Use [OBSERVED_RESULTS.md](evidence_set/OBSERVED_RESULTS.md) for every non-Exact
comparison and emitted finding rule. Its JSON companion contains the detailed
finding instances, source references, coverage and stage timings.
