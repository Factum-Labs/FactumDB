# FactumDB — Frontend (Presentation Layer)

Investigator-facing UI for FactumDB. Recreated from the Claude Design handoff in
[../docs/design-handoff/](../docs/design-handoff/).

**Current state: UI demo.** Every screen renders from hardcoded fixtures in
[src/data/caseData.ts](src/data/caseData.ts). There is no backend logic here and
no Tauri command is invoked yet — matching the architecture rule that the
frontend contains no forensic algorithms, no database access, and no direct
tool execution.

## Stack

| Concern | Choice |
|---|---|
| UI | React 19 + TypeScript |
| Styling | Tailwind CSS 3 (design tokens mirrored in `tailwind.config.js`) |
| State | Zustand |
| Build | Vite |

## Running

From the repo root:

```bash
npm --prefix frontend install
```

```bash
npm run frontend:dev
```

Serves on <http://localhost:1420>.

To run inside the Tauri desktop shell instead (from the repo root, so the CLI
can find `src-tauri/`):

```bash
npm run tauri:dev
```

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server on port 1420 |
| `npm run build` | Typecheck then production build into `dist/` |
| `npm run lint` | oxlint |
| `npm run check:graph` | Acceptance harness for the correlation-graph logic |

## Layout

```
frontend/
  src/
    App.tsx                 shell: titlebar, nav (sidebar/rail/topbar), header, status bar
    store.ts                Zustand store — screen, selections, expanded graph groups
    data/
      types.ts              service-contract types (Transaction, CorrelationEdge, ReconRow…)
      caseData.ts           hardcoded fixtures for case FDB-2026-014
    lib/
      tokens.ts             design tokens lifted from the handoff
      correlation.ts        flagged-record grouping + deterministic graph layout
      correlation.check.ts  acceptance harness for the above
    components/
      Badge.tsx             badge/dot/card primitives
      CorrelationGraph.tsx  reusable bipartite graph renderer
    screens/                one component per screen (10 screens)
```

## Screens

Cases · Evidence intake · Pipeline · Transaction timeline · Record history ·
**Reconciliation** · Evidence gaps · Provenance · Report export · Settings

The nav shell cycles between sidebar / icon rail / top tabs via the "Shell:"
button in the page header — all three layouts from the design handoff are built.

## Reconciliation correlation graph

The one feature added beyond the design handoff. A bipartite transaction→record
graph shown inline on the Reconciliation page, for flagged records only.

It is a **presentation-layer feature over data the domain layer already
produces**. It adds no domain logic: grouping and layout are pure functions over
`RecordCorrelationService` edges and `ReconciliationService` classifications.

**Flagged record** — any record with at least one field classified `Conflicting`
or `Unresolved`. A record can have some `Exact` fields and still be flagged; its
node takes the more severe of its own field results (`Conflicting` outranks
`Unresolved`).

**Grouping** — flagged records are clustered into connected components: two
flagged records share a group when at least one transaction links to both. One
graph per group, not one per record. Computed once per case via `useMemo`, never
per row render.

**Canonical order** — transactions by binlog file then position; records by
table name then primary key. This ordering drives the layout directly.

**Trigger placement** — the first flagged field of the first record in each group
gets a `View correlation graph` toggle; every other row belonging to a flagged
record in that group gets a non-interactive `Shown in graph above` label, so the
same graph never renders twice. Collapsed by default. With zero
Conflicting/Unresolved rows, no graph UI renders at all.

**Scope per group** — left column is every transaction linking to any flagged
record in the group; right column is those flagged records plus any other record
the same transactions touched (rendered muted, for context). No further hops —
the whole case graph is never pulled in.

**Layout** — deterministic only. Node positions are computed arithmetically from
the canonical sort order in `computeGraphLayout`. No force simulation, no
physics, no randomness, no text measurement. The same case data produces
byte-identical geometry on every render, which the evaluation plan's
repeatability metric depends on.

**Visual encoding**

| Element | Encoding |
|---|---|
| Transaction node | green Committed · gray Rolled back · amber Incomplete |
| Record node | red Conflicting · orange Unresolved · muted green agrees · gray never compared |
| Record subtitle | the field(s) that triggered the flag, e.g. `balance: Conflicting` |
| Edge | solid UPDATE · dashed INSERT · dotted DELETE, arrow transaction→record |

`Conflicting` (red, hue 25) and `Unresolved` (orange, hue 55) are deliberately
separate hues — they are different failure modes (evidence disagrees vs.
evidence is insufficient) and must be distinguishable at a glance, not just
distinguishable from `Exact`. Orange also sits clear of the amber (hue 75-85)
used by the `Incomplete` transaction badge.

**Reuse** — `<CorrelationGraph group={flaggedGroup} />` takes a pre-computed
group and renders it. The separately-scoped case-wide bipartite graph view can
reuse it with a different group-selection strategy and no changes to the
component.

**Verification**

```bash
npm run check:graph
```

Covers grouping, canonical ordering, repeatability, the "one graph for a
transaction touching two flagged records" rule, the "no graph without a flagged
member" rule, and the "no fabricated edges" guarantee.

Rendered samples captured from the running app live in
[../docs/graph-samples/](../docs/graph-samples/).

### Demo data shape

The fixtures produce two groups, which is what exercises the grouping rules:

- **Group 1** — TX-1449 (rolled back) and TX-1452 (committed) both touch
  `accounts:101`, so `accounts:101` (Conflicting), `accounts:205` (Unresolved)
  and `transfers:9002` (Conflicting) land in one graph. `transfers:9001` appears
  muted as a non-flagged neighbour. `accounts:101` receiving edges from two
  transactions is the hub pattern.
- **Group 2** — TX-1448 (incomplete) touches only `accounts:310` (Unresolved).

TX-1451 is correctly absent from both: it touches only the non-flagged
`transfers:9001`.

## Wiring up the real backend

[src/data/caseData.ts](src/data/caseData.ts) is the only module holding
fixtures. Its exports match the shapes `TransactionGroupingService`,
`RecordCorrelationService` and `ReconciliationService` are contracted to return,
so replacing it with results from Tauri commands needs no changes in any screen
or in the graph logic.
