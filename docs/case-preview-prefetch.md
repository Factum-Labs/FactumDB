# Case preview prefetch

> Superseded application loading flow: see [Progressive case loading](progressive-case-loading.md).
> The legacy preview/full commands remain compatible, but case opening now uses a
> cheap header and independent screen pages, without automatic full-case loading.

After the case list paints, the authenticated session queues lightweight case previews in the list's newest-created-first order. One preview or selected full-data request runs at a time. View switches to Evidence immediately, uses a cached preview or prioritizes its pending request, and revalidates cached snapshots. Full analysis loads after the selected preview paints, ahead of remaining queued background work.

`get_case_preview` returns case metadata/notes, registered evidence metadata, the latest pipeline stages and attempts, scalar summaries, dashboard counts, and stage warning flags. SQLite computes analysis counts without Python decoding full analysis arrays. Exact and Unresolved are field comparison counts. Unavailable metrics are null. A savepoint keeps all preview reads in one consistent snapshot. Existing full-data, detail, and export commands remain compatible; no schema migration is required.

The session controller retains previews for all accessible cases. It deduplicates preview requests, prioritizes selected work, and invalidates responses using session and per-case generations. Switching cases releases the previous full response. Evidence/notes/pipeline mutations refresh selected previews; Refresh cases invalidates all previews and refills the queue. Lock and sign-out clear cached and queued work. Running transport requests finish, but obsolete responses cannot update state.

Evidence and Pipeline render before full analysis arrives. Pipeline uses preview metrics and retrieves bounded execution output only after execution history is available from selected full data. Other screens display an explicit loading/error/retry boundary. Background work does not set global busy. Completing full loading preserves the current screen, record selections, and mounted notes editor.

## Measurements

The read-only benchmark used the saved 15,802-history credit-union case. Three iterations include projection and JSON serialization, exclude native IPC, and leave the source database unchanged.

| Projection | Median time | JSON bytes |
| --- | ---: | ---: |
| Preview | 2,513.94 ms | 12,245 |
| Existing full case | 11,974.71 ms | 66,705,536 |

Headless Chrome checks measured cached View-to-Evidence display at 34–40 ms with delayed mock IPC. Retaining 20 independently loaded copies of the saved preview increased garbage-collected browser heap by approximately 212–213 KB. This measures preview retention, not the full selected-case response or native bridge. First-time previews still incur SQLite aggregate costs, and selected full-data loading remains expensive; prefetching does not remove that cost.

## Checks

- `npm --prefix frontend run check:case-preview`: queue ordering, priority, deduplication, dispatch serialization, invalidation, retry, and session cleanup.
- `npm --prefix frontend run check:case-preview-browser`: actual App navigation, preview-before-full painting, Pipeline/loading boundaries, errors/retry, note edits and saving, rapid selection, lock/sign-out.
- `npm --prefix frontend run check:backend`: frontend store through the authenticated Python sidecar and SQLite workflow. It waits for explicit full-data readiness where needed.
- Backend projection tests verify authentication, case isolation, null metrics, field-count parity, evidence/pipeline parity, and omission of large arrays/output.

Reproduce backend measurements:

```powershell
python backend/checks/case_preview_benchmark.py "path/to/case.db" --preview-output "$env:TEMP/factumdb-case-preview.json"
$env:FACTUMDB_CASE_PREVIEW = "$env:TEMP/factumdb-case-preview.json"
npm --prefix frontend run check:case-preview-browser
```
