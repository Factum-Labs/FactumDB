import { useMemo } from 'react'
import { Badge } from '../components/Badge'
import { CorrelationGraph } from '../components/CorrelationGraph'
import { correlationEdges, reconRows, records, transactions } from '../data/caseData'
import { RESULT_TONE, type ReconResult } from '../data/types'
import { buildFlaggedGroups, decorateRows } from '../lib/correlation'
import { useApp } from '../store'

const GRID = '200px 130px 1fr 1fr 118px 186px'

const SUMMARY_ORDER: ReconResult[] = [
  'Exact',
  'Strong',
  'Partial',
  'Conflicting',
  'Unresolved',
  'Unsupported',
]

export function ReconciliationScreen() {
  const expanded = useApp((s) => s.expandedGroups)
  const toggleGroup = useApp((s) => s.toggleGroup)
  const recordById = useMemo(() => new Map(records.map((r) => [r.id, r])), [])

  // Grouping is computed once per case data, not per row render.
  const groups = useMemo(
    () => buildFlaggedGroups(records, transactions, correlationEdges, reconRows),
    [],
  )
  const decorations = useMemo(() => decorateRows(reconRows, groups), [groups])

  const counts = useMemo(() => {
    const c = new Map<ReconResult, number>(SUMMARY_ORDER.map((r) => [r, 0]))
    for (const row of reconRows) c.set(row.result, (c.get(row.result) ?? 0) + 1)
    return c
  }, [])

  return (
    <div className="flex max-w-[1180px] flex-col gap-3">
      {/* Summary cards */}
      <div className="grid grid-cols-6 gap-2">
        {/* Uniform chrome: the result's own colour is carried by the Badge in the
            table below, so tinting the counts here only adds a second, competing
            legend. A zero count is dimmed instead. */}
        {SUMMARY_ORDER.map((result) => {
          const n = counts.get(result) ?? 0
          return (
            <div key={result} className="rounded-md border border-line bg-panel px-3 py-2.5">
              <div
                className={`font-mono text-[19px] font-semibold ${n > 0 ? 'text-ink' : 'text-dimmer'}`}
              >
                {n}
              </div>
              <div className="mt-px text-[11px] text-muted">{result}</div>
            </div>
          )
        })}
      </div>

      {/* Comparison table */}
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div
          className="grid border-b border-line bg-thead px-3 py-[7px] text-[10.5px] font-semibold uppercase tracking-[.07em] text-dim"
          style={{ gridTemplateColumns: GRID }}
        >
          <div>Record</div>
          <div>Field</div>
          <div>Log-derived</div>
          <div>Physical (.ibd)</div>
          <div>Result</div>
          <div />
        </div>

        {reconRows.map((row, i) => {
          const record = recordById.get(row.recordId)!
          const { anchorOf, coveredBy } = decorations[i]
          const isOpen = anchorOf ? expanded.includes(anchorOf.id) : false

          return (
            <div key={`${row.recordId}:${row.field}`}>
              <div
                className="grid items-center border-b border-line-soft px-3 py-2 text-[12px]"
                style={{ gridTemplateColumns: GRID }}
              >
                <div className="font-mono">{record.label}</div>
                <div className="text-muted">{row.field}</div>
                <div className="font-mono">{row.log}</div>
                <div className="font-mono">{row.phys}</div>
                <div>
                  <Badge tone={RESULT_TONE[row.result]}>{row.result}</Badge>
                </div>
                <div className="flex justify-end">
                  {anchorOf && (
                    <button
                      onClick={() => toggleGroup(anchorOf.id)}
                      aria-expanded={isOpen}
                      className="inline-flex h-[22px] items-center gap-1.5 rounded border border-line-input bg-panel px-2 text-[11px] text-ink-3 hover:bg-page"
                    >
                      <span
                        className="inline-block text-[9px] text-dimmer transition-transform"
                        style={{ transform: isOpen ? 'rotate(90deg)' : 'none' }}
                      >
                        ▶
                      </span>
                      {isOpen ? 'Hide correlation graph' : 'View correlation graph'}
                    </button>
                  )}
                  {coveredBy && (
                    <span className="text-[10.5px] italic text-dimmer">Shown in graph above</span>
                  )}
                </div>
              </div>

              {anchorOf && isOpen && (
                <div className="border-b border-line-soft bg-page px-3 py-3">
                  <CorrelationGraph group={anchorOf} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex items-start gap-[9px] rounded-md border border-line bg-panel px-3 py-[11px]">
        <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full bg-dimmer" />
        <div className="max-w-[820px] text-[11.5px] text-ink-3">
          Classification is rule-based and describes agreement between available evidence only.
          FactumDB does not attribute a change to a person and does not determine intent.
        </div>
      </div>
    </div>
  )
}
