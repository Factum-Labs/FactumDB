# FactumDB frontend

React and TypeScript presentation layer for the Tauri desktop application.
Screens load persisted cases, evidence and analysis through the Python backend.
The frontend does not access databases or execute extraction tools directly.

## Running

From the repository root:

```bash
npm install
npm --prefix frontend install
npm run tauri:dev
```

The Vite server alone shows a desktop connection message; backend operations
require Tauri. See [desktop setup](../docs/desktop-runtime.md) for runtime and
bundling instructions, and [settings](../docs/settings.md) for account,
session, timezone and storage configuration.

## Structure

- `src/App.tsx`: title bar, tabs, page headers and status/error feedback.
- `src/store.ts`: authenticated state, case actions and pipeline coordination.
- `src/lib/backend.ts`: typed Tauri requests and native file/folder dialogs.
- `src/screens/`: case management, evidence, pipeline, analysis and settings.
- `src/lib/correlation.ts`: grouping and deterministic graph layout over
  backend results; it does not infer or fabricate forensic edges.
- `src/components/`: reusable presentation components.
- `checks/`: integration/browser checks and their regression fixtures.

## Checks

Run from `frontend/`:

| Command | Coverage |
| --- | --- |
| `npm run build` | Type checks and production bundle |
| `npm run lint` | Frontend lint |
| `npm run check:backend` | Frontend store, Python backend and SQLite workflow |
| `npm run check:graph` | Correlation grouping, ordering and repeatable layout |
| `npm run check:gaps` | Finding/warning grouping and rendering |
| `npm run check:gaps-browser` | Pagination and detail expansion in a browser |
| `npm run check:settings-browser` | Account, timezone, storage, locking and case deletion controls |

Browser checks use an installed Chrome-compatible browser and built CSS
(`npm run build` first). Set `FACTUMDB_BROWSER` to select another browser
executable. Graph fixtures live in `checks/correlation.fixtures.ts` and are
not application data.
