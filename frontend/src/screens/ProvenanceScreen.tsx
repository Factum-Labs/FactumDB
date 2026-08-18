import { provChain, rawLines } from '../data/caseData'

export function ProvenanceScreen() {
  return (
    <div className="flex max-w-[900px] flex-col gap-3">
      <div className="rounded-md border border-line bg-panel px-3.5 py-[13px]">
        <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">Finding</div>
        <div className="mt-1 text-[13px]">
          Account 101 balance was committed as 4000.00 in TX-1452, but the physical row in
          accounts.ibd holds 3500.00 — the value written by rolled-back TX-1449.
        </div>
      </div>

      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">
          Evidence chain
        </div>
        {provChain.map((p) => (
          <div
            key={p.k}
            className="grid items-start gap-3 border-b border-line-soft px-[13px] py-[9px]"
            style={{ gridTemplateColumns: '150px 1fr' }}
          >
            <div className="pt-px text-[11px] font-medium text-dim">{p.k}</div>
            <div className="break-all font-mono text-[11.5px]">{p.v}</div>
          </div>
        ))}
      </div>

      <div className="overflow-auto rounded-md bg-ink px-3 py-[11px]">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
          Raw utility output (preserved)
        </div>
        {rawLines.map((l, i) => (
          <div
            key={i}
            className="whitespace-pre-wrap font-mono text-[11px] leading-[1.65]"
            style={{ color: l.color }}
          >
            {l.text}
          </div>
        ))}
      </div>
    </div>
  )
}
