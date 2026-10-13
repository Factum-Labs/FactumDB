# Record-history page bundles

This document records the earlier bundled-page implementation and its measurements.
The current screen loads indexed summaries and only the selected record's details
through the shared progressive cache; see [progressive case loading](progressive-case-loading.md).
The backend `include_details` API remains supported for integrations.

`get_history_page` accepts `include_details: true`. Each item then contains
`summary`, `detail`, and `findings`. Omitting the flag preserves the summary-only
response. Both forms use the same filters, ordering, totals and 100-record limit.

The repository reads the selected source-array ordinals from reconstruction JSON
in one query. Event references are deduplicated and queried in batches of 200,
with evidence ownership restricted to the current case. A SQLite savepoint holds
a consistent snapshot across summaries, reconstruction, and events. The bundled
and single-history projections share event enrichment, finding descriptions and
large-value serialization. No history copies or schema migrations are added.

Record history requests bundles and keeps at most the previous, current and next
pages for the active filter. Selecting a record uses its loaded detail without
another request. Only that record's timeline is rendered. Cached page navigation
displays immediately; uncached navigation clears the previous detail and shows
loading. Superseded responses are ignored. Other screens retain their existing
detail requests.

Adjacent prefetch starts after the current page has painted, next page first.
Already cached pages are reused: normal forward navigation never refetches the
previous page. A direct jump may require fetching both missing neighbors.
Foreground page requests take priority over unsent background work, but an
active request must finish. One shared request lane prevents overlapping page
requests, including when an old screen's request is still finishing after unmount.
Background failures do not disrupt the visible page; navigation retries them.

Case-data replacement and filter changes invalidate the page cache. Table options
are fetched once per case-data generation. The cache is released on screen exit,
lock and sign-out; same-case filter/offset preferences remain available on return.
There is no persistent cache, truncation or backend storage change.

## Measurements

Measured locally on 2026-10-11 using a disposable copy of the saved 15,802-history
credit-union case. Times are medians of five backend query/projection runs, excluding
IPC transport, JSON encoding, and rendering. These are local measurements, not a
latency guarantee.

| Fixture | Summaries + one detail | Bundled 100 histories |
| --- | ---: | ---: |
| Credit-union page: backend time | 926 ms | 978 ms |
| Credit-union page: serialized bytes | 45,136 | 1,082,047 |
| Stress case: backend time | 314 ms | 4,189 ms |
| Stress case: serialized bytes | 478,799 | 44,599,832 |

The backend stress case repeats the first saved history's steps 100 times for
each of 100 histories. It runs only in the disposable copy.

Headless browser heap after garbage collection was 4,154,512 bytes for the saved
page's summaries plus selected detail and 5,065,952 bytes for the bundled page,
an increase of 911,440 bytes. The browser baseline uses the same renderer with
only the selected history populated. A separate synthetic browser page with 100
histories of 400 steps each had a 30,546,131-byte payload and added approximately
31.9 MB of retained heap. Heap measurements exclude native WebView memory and
transient parsing peaks.

### Adjacent-page prefetch measurements

Measured locally on 2026-10-11 with the browser harness and three distinct saved
credit-union pages. The harness serves saved responses over local HTTP; its cold
load measurements include transport, parsing and rendering, **not backend query
time or actual Tauri IPC**. Cached timings include the test's polling interval.

| Browser fixture | Cold page | Cached Next | One-page heap | Three-page heap |
| --- | ---: | ---: | ---: | ---: |
| Saved credit-union | 94 ms | 17 ms | 5.2 MB | 7.7 MB |
| Synthetic 400-step histories | 492 ms | 62 ms | 36.1 MB | 100.7 MB |

The synthetic window contains 300 complete histories; each 100-history payload is
approximately 30.5 MB. Heap values were collected after garbage collection and
exclude native memory and transient parsing peaks. The controller tests assert
that no more than three completed pages are retained.

The separate backend benchmark measured a cold bundled credit-union page at
826 ms (median of five query/projection runs). Prefetch leaves this query unchanged;
its benefit comes from reusing the completed response during navigation.

## Repeat the checks

Run the backend regression suite with `python -m pytest backend/tests -q`.
Frontend checks include `npm --prefix frontend run build`, `lint`, `check:backend`,
`check:progressive`, and `check:history-browser`. Shared-cache checks cover cache
reuse, deduplication, request priority, prefetch and failures.
Browser checks verify post-display prefetch, cached navigation, filtering, stale
responses, cross-screen navigation, case switching, analysis refresh, lock,
sign-out, unmount and background-failure recovery.

For backend measurements, run:

```powershell
python backend/checks/history_page_benchmark.py "path/to/case.db" --page-output "$env:TEMP/history-page.json"
```

For browser measurements of that page:

```powershell
$env:FACTUMDB_HISTORY_PAGE = "$env:TEMP/history-page.json"
npm --prefix frontend run check:history-browser
```

The optional JSON output contains case data; keep it with your local test artifacts.
The benchmark also writes sibling `-100.json` and `-200.json` page files for the
three-page browser measurement. It leaves the original database unchanged.
