# Real MySQL attack evidence lab

Six independent, entirely fictional MySQL databases for manual FactumDB testing.
Each subject contains actual binary MySQL binlogs, InnoDB `.ibd` tablespaces,
`EXPECTED_FINDINGS.md`, acquisition hashes in `manifest.json`, and the SQL used
to create its baseline and activity. These are not text files renamed as binary
evidence. Generated with MySQL Community Server **8.0.43**, ROW logging, normally
FULL row images, CRC32 event checksums, 16 KiB pages and UTC server time.

These are simplified business regression fixtures. See the
[validity and realism audit](REALISM_AUDIT.md) for checks of all six subjects,
independent reproductions using foreign keys and conventional types, and limits
on production realism and attack interpretation.

| Subject | Business | Seeded rows | Tablespaces | Binlogs | Additional evidence issue |
|---|---|---:|---:|---:|---|
| [01_marketplace_fraud](subjects/01_marketplace_fraud/EXPECTED_FINDINGS.md) | Harbor Market | 16,300 | 7 | 3 | Complete acquisition; hidden writes should conflict |
| [02_credit_union_log_erasure](subjects/02_credit_union_log_erasure/EXPECTED_FINDINGS.md) | Cedar Credit Union | 16,300 | 7 | 2 | Middle log withheld; index retains its entry |
| [03_clinic_interrupted_coverup](subjects/03_clinic_interrupted_coverup/EXPECTED_FINDINGS.md) | Maple Clinic | 16,300 | 7 | 3 | Final commit and log tail missing |
| [04_payroll_page_damage](subjects/04_payroll_page_damage/EXPECTED_FINDINGS.md) | Summit Payroll | 16,300 | 7 | 3 | One disbursement index-page checksum damaged |
| [05_logistics_scope_gaps](subjects/05_logistics_scope_gaps/EXPECTED_FINDINGS.md) | Meridian Freight | 16,300 | 6 | 3 | Invoice tablespace and binlog index withheld |
| [06_clean_marketplace](subjects/06_clean_marketplace/EXPECTED_FINDINGS.md) | Willow Market | 15,500 | 5 | 3 | Clean control: complete, intact, consistent |

Each database has 2,500 people, 2,500 business records, 5,000 composite-key line
items, 5,000 installment entries and 500 staff. Attack subjects add 500 keyless
access notes and 300 rich-type documents. There are plausible names, regional
branches, dates, business references, varied values, nullable notes and business
relationships. Money uses integer minor units; the two baseline installments sum
to the corresponding header total. Addresses use reserved fictional domains.
Each subject has approximately 2.4–2.8 MiB of binary evidence: over 97,000 seeded
rows across the lab, rather than padded files or repeated copies of one database.

## Use in the app

1. Create a separate case for each subject.
2. Import all files from that subject's `ibd/` and `binlog/` directories. Include
   `mysql-bin.index` if present. Its original private-server paths are intentional:
   the app uses their filenames to establish the inventory.
3. Run complete analysis with deleted-row extraction disabled for the baseline
   comparison. Follow that subject's `EXPECTED_FINDINGS.md` checklist.
4. Optionally repeat in another case with deleted-row extraction enabled. Deleted
   remnants depend on InnoDB purge and are not required findings for these cold
   snapshots.
5. Compare with `APP_VALIDATION.md` / `APP_VALIDATION.json` when present; these
   contain actual results from the current backend and installed extraction tools.
   They are separate from fixture ground truth and can reveal app bugs.

Start with the clean control, then subject 01, then the evidence-loss/damage cases.
Only use `ibd/` and `binlog/` as forensic input. SQL, Markdown and manifests are
reference material. The `.ibd` files are intended for offline extraction; they are
not a complete restorable MySQL server backup.

### Backend repair validation

Engine revision 2 fixes the multi-row identity, truncated-transaction, MINIMAL
update, type-normalization and presence-comparison failures. Full desktop backend
runs with installed tools now pass all six subjects' acceptance assertions. The
clean control accounts for all 15,550 decoded row changes and reconciles all
15,500 live records Exact, with no unexpected warnings.

See [the repair validation report](REPAIR_VALIDATION.md) and each subject's
`APP_VALIDATION.md` for separate record/field counts and exact-key checks. Older
backend-limitation notes in the original expected-findings files describe the
pre-repair engine. Original SQL, ground truth, evidence bytes and hashes have
been preserved. Existing application cases require reanalysis after upgrading.

## Coverage and interpretation

Every attack subject mixes logged fraud with unlogged financial/contact/role
rewrites, hidden deletion, an off-ledger insert, a before-image discontinuity,
mass deletion, key reuse, a composite-key change, partial row images, a keyless
audit table and unsupported values. The subject-specific evidence faults test
whether the app distinguishes positive disagreement from inadequate evidence.
Checklists identify exact tables, keys, altered values and applicable rule IDs.

A logged malicious change can still reconcile perfectly: consistency does not
establish authorization. The current app reconstructs evidence; it does not have
a universal attack classifier. SQL injection entry points, SELECT-only data
theft, credential compromise, network traffic, host malware, availability attacks
and server-account permissions require additional evidence. These fixtures do
not pretend such facts can be recovered from unrelated row files.

The clean control has no injected data or evidence errors. It deliberately stays
within the current INT/TEXT/DATE comparison scope to avoid conflating unsupported
schema types with a dirty database. Rolled-back InnoDB changes are benign control
operations and are not persisted as durable binlog row events.

## Reproduce or increase the size

From the repository root on Windows:

```powershell
py -3.11 datasets/attack_lab/generate.py --mysql-bin 'C:/Program Files/MySQL/MySQL Server 8.0/bin' --output datasets/attack_lab/subjects_large --scale 10000
```

`--scale` is the count of main people/business records per database (default
2,500; minimum 500). The example produces 62,800 baseline rows in each attack
subject and 62,000 in the clean control. Existing output directories are refused;
choose a fresh destination. After cloning, the tracked SQL/manifests already
occupy `subjects/`; generate into a fresh directory such as `subjects_local/`
and import its files. The verification scripts accept `--subjects` for this
alternative directory. Use MySQL **8.0** for this script (`RESET MASTER` is
version-specific). The generator only connects to its own newly initialized
server on loopback port 34317, refuses an occupied port, ignores system MySQL
configuration, and shuts down its private server after each acquisition.
Existing MySQL services/databases are not used. Private data and logs are left
under `.scratch/` for diagnosing generation failures.

Acquisition uses a clean shutdown so the original files are stable before copying.
Intentional mutations affect only the newly generated lab copies. MySQL documents
the relevant [binary logging options](https://dev.mysql.com/doc/refman/8.0/en/replication-options-binary-log.html)
and [private data-directory initialization](https://dev.mysql.com/doc/refman/8.0/en/data-directory-initialization.html).

To check all binary evidence against its acquisition hashes:

```powershell
py -3.11 datasets/attack_lab/verify_hashes.py
```

To validate the default subjects through the current desktop backend (full
analysis of these row counts can take several minutes per subject):

```powershell
py -3.11 datasets/attack_lab/verify_app.py --mysql-bin 'C:/Program Files/MySQL/MySQL Server 8.0/bin' --ibd2sql src-tauri/resources/runtime/windows/ibd2sql/main.py
```

Use `--subject 06_clean_marketplace` to validate just one. App case workspaces go
under `.validation-cases/`; the evidence sources remain untouched. Validation
requires the backend's normal Python dependencies and the ibd2sql tool.

## Repository storage

SQL, documentation, manifests and verification scripts are reviewable source
files. Binary evidence is saved locally in this repository, but remains ignored
by the repository's existing `*.ibd` and `mysql-bin.*` policy. It will not be
included in a normal Git commit. Regenerate it after cloning, or distribute the
subject folders separately when sharing the lab. Local MySQL scratch data and
validation case workspaces are also ignored.
