# Progressive case loading

Case opening uses `get_case_header`; it does not schedule `get_case_data`.
Evidence and notes render from the header. Pipeline/dashboard counts come from
stored stage summaries. A covering index on `(case_id, stage, saved_at)` keeps
revision checks from reading large `result_json` overflow pages.

## Data requested by each screen

| Screen | Initial request | Deferred data |
| --- | --- | --- |
| Evidence | Header, evidence metadata, notes | User actions only |
| Pipeline/dashboard | Saved counts/status and latest 100 tool runs | Bounded tool output; earlier runs through Provenance |
| Transactions | 100 summaries | Selected transaction metadata; 100 events per page |
| Record History | Table options and 100 summaries | Selected history metadata, first steps, 100 steps per page and their source events |
| Reconciliation | 100 record rollups, global result counts | 100 field comparisons per expanded record; selected comparison provenance; explicit graph loading |
| Gaps & warnings | Finding and extraction-warning group summaries | 100 occurrences per expanded group; coverage on expansion |
| Provenance | 100 tool runs | Selected run and bounded output |
| Report | 100 export-history entries | Existing progressive export preparation and preview pages |

Reconciliation filtering happens in SQLite across the complete saved result.
Counts describe the complete result, not just the loaded page. History table
filters and external record/transaction navigation resolve before showing the
requested selection. Record details explicitly identify a first-page comparison
preview when a record has more than 100 fields. Archival exports stay complete.

## Storage and older cases

New analysis saves rebuild indexed summaries, transaction events, history steps,
comparison details and grouped finding counts in the same transaction as the
authoritative result. Compact reconciliation finding references stay compact;
only selected comparison findings are expanded. Replacing, deleting or restarting
analysis invalidates dependent indexes using SQLite triggers.

Older cases retain their authoritative JSON. Their first screen visit creates
small **SQL-projected summary indexes**, not expanded copies of the full result.
Selected details read one saved item; findings are deduplicated and projected once
when their main table is first opened. Later pages use those projections.
Pipeline/dashboard can populate missing legacy counts on demand. Unknown counts
remain placeholders until available. No reanalysis is required.

The first visit to a large older case's analysis screen can still take seconds.
This cost is kept out of the initial case header and is measured separately.

## Scheduling, retention and refresh

All frontend IPC uses one lane. Foreground requests precede queued speculative
work; selecting a prefetched page promotes its request. Running work cannot be
interrupted. Opening a case queues one bounded first page (100 summaries) for
Transactions, Record history, Reconciliation, finding groups, warning groups,
Provenance and export history. The visible main table finishes first; its next
page has higher background priority than the remaining first pages. Navigation
promotes a matching queued request to foreground without duplicating it. Queued
warm-up work remains valid across navigation, but stops on case/revision changes,
lock or sign-out. Expanded findings, comparisons and selected details remain on
demand. Report projection, analysis composition and PDF dependencies are imported
lazily. Their warm-up commands have the lowest background priority (3, below
adjacent pages at 1 and first-page warm-up at 2), with a 250 ms grace period on entering idle work. Continuing report batches
do not repeat that delay; foreground/page work re-arms the grace period.
Newly queued page or foreground work takes precedence even if the import was
queued earlier. Feature use imports its required dependencies immediately.
Imports already running cannot be interrupted; bundles are separate jobs.
Legacy projection creation can still occupy the running lane; a bounded
response does not guarantee a short backend query.

The session screen cache keys include case, revision, command, filters and page.
It deduplicates requests, uses LRU eviction, and has a 12 MiB estimated serialized
retention budget plus a 96-entry limit. Header caching has a 2 MiB estimate and
64-entry limit; automatic header prefetch covers the 20 newest cases. These are
payload budgets, not measurements of total JavaScript heap.

Visited screens stay mounted within a case opening. Same-case refresh keeps rows,
filters, selections, scroll positions and the notes editor visible while replacing
changed data. Errors provide local retry controls. Unknown sections get reserved
placeholders; loaded content is retained during revalidation. Lock/sign-out clear
session caches and unmount case views. Obsolete queued and late responses cannot
repopulate them. Closing/reopening still resets view state, preserving the existing
`caseOpening` behavior.

## Regression measurements (2026-10-13)

The saved 15,802-history credit-union case was opened read-only and backed up to a
temporary database. Only the temporary copy was initialized or projected.
Measurements include SQLite projection and JSON serialization; exclude native IPC,
desktop session setup and actual WebView rendering. Three iterations provide
medians; cold screen visits use one iteration.

| Read | Previous | Progressive |
| --- | ---: | ---: |
| Initial preview/header | 3,617.95 ms | 2.10 ms |
| Full case response | 13,919.77 ms / 66.7 MB | No automatic request |
| Transactions first legacy page | Full case required | 328.11 ms / 12.5 KB |
| History first legacy page | Full case required | 2,510.22 ms / 32.5 KB |
| Reconciliation first legacy page | Full case required | 2,299.04 ms / 12.6 KB |
| Finding groups first legacy visit | Full case required | 4,863.71 ms / 7.2 KB |
| All four initial page reads plus header | — | 10,003.18 ms combined |
| Subsequent transaction/history/reconciliation pages | — | 0.63 / 1.79 / 1.98 ms |
| Subsequent finding group summary | — | 0.18 ms |

The benchmark asserts that the initial header is faster than the previous preview
and each first screen visit is faster than the previous full projection. It also
checks the combined cost of all four first-page reads plus the header. Results
are evidence for this saved case, not a guarantee for all hardware or datasets.
Rerun after changing projections or indexes:

```powershell
py -3.11 backend/checks/progressive_screen_benchmark.py "path/to/case.db"
```

## Verification

- `npm --prefix frontend run check:progressive`: request priority, stale queued work, cache deduplication, eviction and late-response cleanup.
- `npm --prefix frontend run check:progressive-browser`: actual App navigation, next-page reuse, all main-table first-page warm-up, deferred findings/comparisons, filters, notes, scroll positions, retained rows, retry, and lock cleanup. Mocked IPC; no full-case requests.
- `npm --prefix frontend run check:history-browser`: table filtering, navigation, selected details, stale responses, close/reopen and A/B/A switching.
- `npm --prefix frontend run check:backend`: frontend store through authenticated Python/SQLite, workflow, complete exports and screen rendering.
- `backend/tests/application/test_progressive_screens.py`: bounded pages, counts/filters/findings parity, legacy fallback, invalidation, history steps and guarded routes.
- Production build, frontend lint, gaps/report browser controls and the backend test suite.

## Automatic report preparation

For a completed saved case or a pipeline that has just finished, the opening
queue also prepares both default redacted reports. Main-table pages have priority
1?2, dependency imports have priority 3, and each report preparation batch has
priority 4. New page requests take precedence over queued report batches.
Background advancement uses a 25 ms target between generator yields; an individual
projection item or PDF page can exceed that target and cannot be interrupted.

The backend retains at most the current case's two background report slots,
alongside the active preview. Switching formats parks the previous format's job
or completed preview without cancelling it. PDF and JSON retain independent tokens
and progress; returning to either format restores its preview or active preparation.
Hidden preparations continue at background priority, and Cancel targets only the
selected format. Changing case, revision or content options invalidates the screen's
retained previews. The full JSON is rendered incrementally
into a temporary file, and the PDF into its temporary rendered document. Neither
report's complete bytes enter the screen cache. Report automatically claims a
completed matching sharing preview when opened. Original-value copies remain
explicitly requested. No destination files or export-history records are created
by warming. Prepared snapshots are validated against case data and settings,
expire when inactive (active preparations renew their ten-minute lease), and are disposed on lock, sign-out, case change or backend
shutdown. Interrupted/failed warming leaves manual report preparation available.

Report preparation now yields during large skipped JSON scans, compact-pool
construction and validation, in addition to output-item processing. Stream
checkpoints are internal sentinels and do not alter exported evidence values.
Opening a matching progressive preview adopts its existing background token,
including partially prepared jobs, rather than restarting. Preparation polling
continues at the lowest priority when Report is hidden. Running individual items,
PDF font work and final disk operations can still exceed the batch time target.

## Report throughput

Authentication status/activity requests keep their transport priority but do not
re-arm the report idle grace period. User navigation and page requests still do.
Skipped JSON strings are scanned as complete spans, with existing stream
checkpoints and UTF-8/escape handling retained. PDF grouping uses bounded caches
for group identities and duplicate observations; aggregate counters are batched.
JSON batches aggregate-count updates and tracks output ordinals without a repeated
MAX query for each row. Its complete export selection and all object associations
remain intact. The caches store counts and hashes, not whole analysis arrays.
Finished report previews survive reopening the same unchanged case within their
existing expiry, and remain cleared on lock, sign-out, revision or case changes.
Progress messages identify byte-based scans/writes in MB rather than entries.

The analysis-save and legacy screen-index paths retain the validated reconciliation
storage header in their revision-invalidated summary cache. Reports reuse it,
avoiding a second complete scan just to detect compact storage. A source analysis
update clears the cached header through the existing invalidation triggers.
`backend/checks/report_generation_benchmark.py` measures both full preparations,
interleaves cached page reads, and checks preview claims on a temporary backup.
The supplied case database is opened read-only.

The final local large-case checks measured PDF construction at 30.4 seconds
(previously 45.4), and complete JSON construction at 204.5 seconds for the same
390,686,762-byte output. JSON's raw construction time did not significantly
improve; queue throughput and reuse of completed previews are its confirmed gains.
These backend measurements exclude native IPC and browser canvas rendering.
Interleaved cached page reads remained below 1 ms in the final JSON check, and
claiming its prepared preview took approximately 1 ms. All 74 targeted backend
tests and the queue/progressive/report browser checks passed.
