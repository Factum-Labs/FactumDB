# Record-history page bundles

`get_history_page` accepts `include_details: true`. Each item then contains
`summary`, `detail`, and `findings`. Omitting the flag preserves the summary-only
response. Both forms use the same filters, ordering, totals and 100-record limit.

The repository reads the selected source-array ordinals from reconstruction JSON
in one query. Event references are deduplicated and queried in batches of 200,
with evidence ownership restricted to the current case. A SQLite savepoint holds
a consistent snapshot across summaries, reconstruction, and events. The bundled
and single-history projections share event enrichment, finding descriptions and
large-value serialization. No history copies or schema migrations are added.

Record history requests bundles and keeps only the current page. Selecting a
record uses its loaded detail without another request. Only that record's timeline
is rendered. Page and filter changes clear the previous details; superseded
requests are ignored. Other screens retain their existing detail requests.

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

## Repeat the checks

Run the backend regression suite with `python -m pytest backend/tests -q`.
Frontend checks include `npm --prefix frontend run build`, `lint`, `check:backend`,
and `check:history-browser`. The history browser check verifies immediate
selection, filtering, page changes, stale responses, cross-screen navigation,
case switching and analysis refresh.

For backend measurements, run:

```powershell
python backend/checks/history_page_benchmark.py "path/to/case.db" --page-output "$env:TEMP/history-page.json"
```

For browser measurements of that page:

```powershell
$env:FACTUMDB_HISTORY_PAGE = "$env:TEMP/history-page.json"
npm --prefix frontend run check:history-browser
```

The optional JSON file contains case data; keep it with your local test artifacts.
The benchmark leaves the original database unchanged.
