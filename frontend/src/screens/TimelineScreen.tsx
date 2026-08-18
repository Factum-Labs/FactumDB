import { Fragment } from 'react'
import { Badge } from '../components/Badge'
import { transactions, txDetail } from '../data/caseData'
import { TX_TONE } from '../data/types'
import { A, GRN } from '../lib/tokens'
import { useApp } from '../store'

const OP_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  INSERT: { color: 'oklch(0.42 0.09 150)', bg: 'oklch(0.96 0.03 150)', border: 'oklch(0.88 0.05 150)' },
  UPDATE: { color: 'oklch(0.42 0.11 255)', bg: 'oklch(0.96 0.03 255)', border: 'oklch(0.88 0.05 255)' },
  DELETE: { color: 'oklch(0.45 0.13 25)', bg: 'oklch(0.96 0.03 25)', border: 'oklch(0.89 0.06 25)' },
}

export function TimelineScreen() {
  const selectedTx = useApp((s) => s.selectedTx)
  const selectTx = useApp((s) => s.selectTx)
  const go = useApp((s) => s.go)

  const tx = transactions.find((t) => t.id === selectedTx) ?? transactions[0]
  const detail = txDetail[tx.id]

  return (
    <div className="grid max-w-[1240px] items-start gap-4" style={{ gridTemplateColumns: '268px 1fr' }}>
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">Transactions</div>
        {transactions.map((t) => {
          const on = t.id === tx.id
          return (
            <div
              key={t.id}
              onClick={() => selectTx(t.id)}
              className="cursor-pointer border-b border-line-soft px-3 py-[9px] hover:bg-thead"
              style={{
                borderLeft: `2px solid ${on ? A : 'transparent'}`,
                background: on ? '#faf9f7' : '#fff',
              }}
            >
              <div className="flex items-center gap-[7px]">
                <span className="font-mono text-[12px] font-medium">{t.id}</span>
                <Badge tone={TX_TONE[t.status]}>{t.status}</Badge>
              </div>
              <div className="mt-[3px] text-[11px] text-muted">{t.summary}</div>
              <div className="mt-[3px] font-mono text-[10.5px] text-dimmer">{t.when}</div>
            </div>
          )
        })}
      </div>

      <div className="flex flex-col gap-3">
        <div className="rounded-md border border-line bg-panel px-3.5 py-[13px]">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="font-mono text-[15px] font-semibold">{tx.id}</div>
            <Badge tone={TX_TONE[tx.status]}>{tx.status}</Badge>
            <div className="flex-1" />
            <button
              onClick={() => go('prov')}
              className="h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-[#f3f2ef]"
            >
              Provenance
            </button>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2.5">
            {detail.meta.map((m) => (
              <div key={m.k}>
                <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
                  {m.k}
                </div>
                <div className="mt-0.5 font-mono text-[12px]">{m.v}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-md border border-line bg-panel">
          <div className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">
            Events in commit order
          </div>
          {detail.events.map((ev, i) => {
            const op = OP_STYLE[ev.op]
            return (
              <div key={i} className="border-b border-line-soft px-[13px] py-[11px]">
                <div className="flex items-center gap-[9px]">
                  <span
                    className="inline-flex h-[18px] items-center rounded-[3px] px-[7px] text-[10.5px] font-semibold tracking-[.03em]"
                    style={{ color: op.color, background: op.bg, border: `1px solid ${op.border}` }}
                  >
                    {ev.op}
                  </span>
                  <span className="font-mono text-[12px]">{ev.table}</span>
                  <span className="text-[11px] text-muted">key {ev.key}</span>
                  <div className="flex-1" />
                  <span className="font-mono text-[10.5px] text-dimmer">{ev.pos}</span>
                </div>
                <div
                  className="mt-[9px] grid gap-px overflow-hidden rounded border border-line-mid bg-line-mid"
                  style={{ gridTemplateColumns: '150px 1fr 1fr' }}
                >
                  {['Column', 'Before', 'After'].map((h) => (
                    <div
                      key={h}
                      className="bg-thead px-[9px] py-[5px] text-[10px] font-semibold uppercase tracking-[.07em] text-dim"
                    >
                      {h}
                    </div>
                  ))}
                  {ev.rows.map((r) => (
                    <Fragment key={r.col}>
                      <div className="bg-panel px-[9px] py-[5px] font-mono text-[11.5px]">
                        <span className="text-dimmer">{r.pos}</span> {r.col}
                      </div>
                      <div className="bg-panel px-[9px] py-[5px] font-mono text-[11.5px] text-muted">
                        {r.before}
                      </div>
                      <div
                        className="px-[9px] py-[5px] font-mono text-[11.5px]"
                        style={{
                          background: r.changed ? 'oklch(0.97 0.02 255)' : '#fff',
                          color: r.changed ? 'oklch(0.4 0.12 255)' : '#6b6a65',
                          fontWeight: r.changed ? 500 : 400,
                        }}
                      >
                        {r.after}
                      </div>
                    </Fragment>
                  ))}
                </div>
              </div>
            )
          })}
          <div className="flex items-center gap-2 px-[13px] py-[9px] text-[11.5px] text-muted">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: GRN }} />
            {detail.footer}
          </div>
        </div>
      </div>
    </div>
  )
}
