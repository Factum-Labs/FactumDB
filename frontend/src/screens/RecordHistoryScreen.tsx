import { historyLegend, recordHistory, records, reconRows } from '../data/caseData'
import { useApp } from '../store'
import { A, A_LIGHT, A_SOFT, LINE, LINE_MID, PAGE, PANEL } from '../lib/tokens'

export function RecordHistoryScreen() {
  const selected = useApp((s) => s.selectedRecord)
  const selectRecord = useApp((s) => s.selectRecord)

  const rec = recordHistory[selected] ?? recordHistory[records[0].id]
  const eventCounts = new Map<string, number>()
  for (const r of reconRows) eventCounts.set(r.recordId, (eventCounts.get(r.recordId) ?? 0) + 1)

  return (
    <div className="grid max-w-[1180px] items-start gap-4" style={{ gridTemplateColumns: '250px 1fr' }}>
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">
          Correlated records
        </div>
        {records.map((r) => {
          const on = r.id === selected
          return (
            <div
              key={r.id}
              onClick={() => selectRecord(r.id)}
              className="cursor-pointer border-b border-line-soft px-3 py-[9px] hover:bg-thead"
              style={{
                borderLeft: `2px solid ${on ? A : 'transparent'}`,
                background: on ? A_SOFT : PANEL,
              }}
            >
              <div className="font-mono text-[12px]">{r.table}</div>
              <div className="mt-0.5 text-[11px] text-muted">
                {r.key} · {eventCounts.get(r.id) ?? 0} compared fields
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex flex-col gap-3">
        <div className="rounded-md border border-line bg-panel px-3.5 py-[13px]">
          <div className="flex items-baseline gap-2.5">
            <div className="font-mono text-[15px] font-semibold">{rec.title}</div>
            <div className="text-[11.5px] text-muted">identity linked by {rec.method}</div>
          </div>
        </div>

        <div className="rounded-md border border-line bg-panel pb-3.5">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-line-soft px-3.5 py-2.5">
            <span className="text-[11px] font-semibold text-muted">Step marker</span>
            {historyLegend.map((l) => (
              <span key={l.label} title={l.note} className="flex items-center gap-1.5">
                <span
                  className="h-[7px] w-[7px] flex-none rounded-full"
                  style={{ background: l.color }}
                />
                <span className="text-[11px] text-muted">{l.label}</span>
              </span>
            ))}
          </div>
          <div className="px-3.5 pt-1">
            {rec.steps.map((s, i) => (
              <div
                key={i}
                className="grid gap-3 pb-0.5 pt-3"
                style={{ gridTemplateColumns: '16px 1fr' }}
              >
                <div className="flex flex-col items-center pt-1">
                  <span
                    className="h-[9px] w-[9px] flex-none rounded-full"
                    style={{ background: s.color }}
                  />
                  <span
                    className="mt-1 w-px flex-1"
                    style={{
                      minHeight: 34,
                      background: i === rec.steps.length - 1 ? 'transparent' : LINE,
                    }}
                  />
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-[9px]">
                    <span className="text-[12.5px] font-semibold">{s.title}</span>
                    <span className="font-mono text-[11px] text-dimmer">{s.source}</span>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted">{s.note}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {s.fields.map((f) => (
                      <div
                        key={f.col}
                        className="flex gap-1.5 rounded-[3px] px-2 py-[3px] font-mono text-[11px]"
                        style={{
                          background: f.highlight ? A_SOFT : PAGE,
                          border: `1px solid ${f.highlight ? A_LIGHT : LINE_MID}`,
                        }}
                      >
                        <span className="text-dim">{f.col}</span>
                        <span>{f.val}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
