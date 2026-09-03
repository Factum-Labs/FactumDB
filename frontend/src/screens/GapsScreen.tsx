import { Badge } from '../components/Badge'
import { gaps } from '../data/caseData'

export function GapsScreen() {
  return (
    <div className="flex max-w-[900px] flex-col gap-2.5">
      {/* Uniform card chrome — severity is carried by the Badge alone. */}
      {gaps.map((g) => (
        <div key={g.code} className="rounded-md border border-line bg-panel px-[13px] py-3">
          <div className="flex items-center gap-[9px]">
            <Badge tone={g.tone}>{g.severity}</Badge>
            <span className="text-[12.5px] font-semibold">{g.title}</span>
            <div className="flex-1" />
            <span className="font-mono text-[10.5px] text-dimmer">{g.code}</span>
          </div>
          <div className="mt-1.5 text-[12px] text-ink-3">{g.detail}</div>
          <div className="mt-[9px] flex gap-[18px] border-t border-line-soft pt-[9px]">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
                Impact
              </div>
              <div className="mt-0.5 text-[11.5px]">{g.impact}</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
                Affects
              </div>
              <div className="mt-0.5 font-mono text-[11.5px]">{g.affects}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
