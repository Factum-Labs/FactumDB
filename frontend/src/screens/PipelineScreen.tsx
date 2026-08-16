import { logLines, stages, stats } from '../data/caseData'
import { AMB, GRN } from '../lib/tokens'
import { useApp } from '../store'

export function PipelineScreen() {
  const go = useApp((s) => s.go)
  return (
    <div className="grid max-w-[1240px] items-start gap-4" style={{ gridTemplateColumns: '1fr 400px' }}>
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="flex items-center gap-2.5 border-b border-line px-3 py-[9px]">
          <div className="text-[12px] font-semibold">Processing pipeline</div>
          <div className="flex-1" />
          <button className="h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-[#f3f2ef]">
            Run stage
          </button>
          <button
            onClick={() => go('timeline')}
            className="h-[26px] rounded bg-ink px-[11px] text-[11.5px] font-medium text-white"
          >
            Run complete analysis
          </button>
        </div>
        {stages.map((s, i) => (
          <div
            key={s.name}
            className="grid items-center gap-2.5 border-b border-line-soft px-3 py-[7px]"
            style={{ gridTemplateColumns: '26px 1fr 128px 86px' }}
          >
            <div className="font-mono text-[11px] text-dimmer">{String(i + 1).padStart(2, '0')}</div>
            <div className="flex items-center gap-2">
              <span
                className="h-[7px] w-[7px] flex-none rounded-full"
                style={{ background: s.kind === 'warn' ? AMB : GRN }}
              />
              <span className="text-[12px]">{s.name}</span>
            </div>
            <div className="text-[11px] text-muted">{s.detail}</div>
            <div className="text-right font-mono text-[11px] text-dimmer">{s.time}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2">
          {stats.map((t) => (
            <div key={t.label} className="rounded-md border border-line bg-panel px-[11px] py-[9px]">
              <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
                {t.label}
              </div>
              <div className="mt-0.5 font-mono text-[18px] font-semibold" style={{ color: t.color }}>
                {t.value}
              </div>
            </div>
          ))}
        </div>
        <div className="max-h-[330px] overflow-auto rounded-md bg-ink px-3 py-[11px]">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
            Execution log
          </div>
          {logLines.map((l, i) => (
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
    </div>
  )
}
