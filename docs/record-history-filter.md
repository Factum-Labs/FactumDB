# Record history table filtering

Record history offers **All tables** or one database-qualified table. The backend
returns 100 lightweight summaries per page; selecting a record loads its full
saved history. This display filter does not restrict analysis or case exports.

SQLite stores rebuildable `history_summaries` and `history_summary_ready` data.
Reconstruction saves rebuild the summaries in the same transaction. Deleting or
updating the authoritative reconstruction result invalidates the derived data.
Existing cases are backfilled on their first history-list request, without
reanalysis. Empty history sets are marked initialized too.

Authenticated desktop commands:

- `get_history_tables`: `case_id`; returns `tables` (database, qualified table,
  count) and `total`.
- `get_history_page`: `case_id`, optional `database`/`table` pair, `offset`
  (default 0), `limit` (default 100, maximum 100); returns `items`, `total`,
  `offset`, `limit`. `table` is the qualified name returned by the tables command.
- `locate_history_record`: `case_id`, `identity`, optional `qualified_table`;
  returns database, qualified table, and the containing 100-record page offset.
  Ambiguous legacy identities produce an error rather than choosing a database.
- `get_analysis_detail` accepts an optional `qualified_table` for history details.

The case overview replaces `reconstruction.histories` with `history_count` and
`histories_paginated`. Archival export shapes are unchanged.

## Performance check

A synthetic in-memory SQLite case with 15,802 histories (four steps each) was
measured during implementation. This is a size-matched benchmark, not the actual
credit-union acquisition or a production latency guarantee:

| Measurement | Result |
| --- | ---: |
| Previous full summary array | 3,210,772 bytes |
| New 100-summary array | 19,360 bytes |
| Derived database storage increase | 4,157,440 bytes |
| First backfill | 0.164 seconds |
| Median filtered page query over 20 runs | 0.768 milliseconds |

Tests verify that filtered queries use `idx_history_table`, preserve source-array
order, isolate cases, handle duplicate table names across databases, and clean up
derived data. Full-detail lookup still scans the saved JSON and is intentionally
outside this optimization.
