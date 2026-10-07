# Willow Market (clean control): expected findings

All identities, addresses, documents and money are fictional. Currency is stored in minor units.

Database: `willow_market`. Seeded rows: **15,500**. See `manifest.json` for acquired row counts, hashes and exact acquisition mutations; `baseline.sql` and `activity.sql` contain every generated change.

## Import

Create a separate case. Import every file in `ibd/` and `binlog/`, including `mysql-bin.index` when present. Do not import the SQL or manifests as evidence. Start with deleted-row extraction disabled; enable it in a second case to explore purge-dependent remnants.

## Clean-control acceptance checklist

- [ ] Every acquired `.ibd` passes innochecksum; all binlogs decode with valid event checksums.
- [ ] The index lists exactly the supplied logs, with no missing sequence members.
- [ ] Every row event belongs to a committed transaction; no incomplete groups.
- [ ] All 15,500 live rows have log histories and primary-key identities, including the composite keys in `order_lines`.
- [ ] Final live values and presence agree: no Conflicting or Unresolved records, unsupported fields, checksum failures, or unexpected warning findings when deleted-row extraction is off.
- [ ] Both installment payments sum to the associated header total. There are no injected business errors.
- [ ] Routine changes to `orders` 401-450 are fully logged and reconcile normally; `orders` 91 retains its original amount after a rollback.

This control intentionally uses INT/TEXT/DATE instead of parameterized VARCHAR/DECIMAL, JSON, BLOB or FLOAT because the current engine has decoding/supported-type limits for those types. Dates and names still look like a normal business database. Benign informational findings do not make the database erroneous. MySQL omits rolled-back InnoDB row events, so no rolled-back group should be invented.

If the app flags R-GRP-013 on these ordinary multi-row inserts, that is an engine defect: different rows legitimately share one event position. The current engine retains only the first row per position and reports the other rows as unresolved. `APP_VALIDATION.md`, when present, records this failing control separately from the clean database's expected outcome.
