import { logLines, stages, stats } from '../data/caseData'
import { A, AMB, GRN, GRY } from '../lib/tokens'
import { useApp } from '../store'

export function PipelineScreen() {
  const go = useApp((s) => s.go)
  const stagesDone = useApp((s) => s.stagesDone)
  const runningStage = useApp((s) => s.runningStage)
  const runStage = useApp((s) => s.runStage)
  const runAllStages = useApp((s) => s.runAllStages)
  const resetPipeline = useApp((s) => s.resetPipeline)

  const running = runningStage !== null
  const complete = stagesDone >= stages.length
  // The log is a transcript of work done, so it grows with the run rather than
  // sitting there in full before a single stage has executed.
  const shownLog = logLines.slice(0, Math.round((logLines.length * stagesDone) / stages.length))

  return (
    <div className="grid max-w-[1240px] items-start gap-4" style={{ gridTemplateColumns: '1fr 400px' }}>
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="flex items-center gap-2.5 border-b border-line px-3 py-[9px]">
          <div className="text-[12px] font-semibold">Processing pipeline</div>
          <div className="font-mono text-[11px] text-dimmer">
            {stagesDone} / {stages.length}
          </div>
          <div className="flex-1" />
          {stagesDone > 0 && !running && (
            <button
              onClick={resetPipeline}
              className="h-[26px] rounded px-2 text-[11.5px] text-muted hover:bg-page"
            >
              Reset
            </button>
          )}
          <button
            onClick={runStage}
            disabled={running || complete}
            className="h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-page disabled:cursor-not-allowed disabled:text-dimmer disabled:hover:bg-panel"
          >
            Run stage
          </button>
          <button
            onClick={() => runAllStages(() => go('timeline'))}
            disabled={running || complete}
            className="h-[26px] rounded bg-accent px-[11px] text-[11.5px] font-medium text-white hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
          >
            {stagesDone > 0 && !complete ? 'Run remaining stages' : 'Run complete analysis'}
          </button>
        </div>
        {stages.map((s, i) => {
          const done = i < stagesDone
          const active = i === runningStage
          return (
            <div
              key={s.name}
              className="grid items-center gap-2.5 border-b border-line-soft px-3 py-[7px]"
              style={{ gridTemplateColumns: '26px 1fr 128px 86px' }}
            >
              <div className="font-mono text-[11px] text-dimmer">{String(i + 1).padStart(2, '0')}</div>
              <div className="flex items-center gap-2">
                <span
                  className={`h-[7px] w-[7px] flex-none rounded-full ${active ? 'animate-pulse' : ''}`}
                  style={
                    done
                      ? { background: s.kind === 'warn' ? AMB : GRN }
                      : active
                        ? { background: A }
                        : { boxShadow: `inset 0 0 0 1px ${GRY}` }
                  }
                />
                <span className={`text-[12px] ${done || active ? '' : 'text-dim'}`}>{s.name}</span>
              </div>
              <div className="text-[11px] text-muted">{done ? s.detail : active ? 'running…' : ''}</div>
              <div className="text-right font-mono text-[11px] text-dimmer">{done ? s.time : ''}</div>
            </div>
          )
        })}
      </div>

      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2">
          {stats.map((t) => {
            const ready = stagesDone >= t.stage
            return (
              <div key={t.label} className="rounded-md border border-line bg-panel px-[11px] py-[9px]">
                <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
                  {t.label}
                </div>
                <div
                  className={`mt-0.5 font-mono text-[18px] font-semibold ${ready ? 'text-ink' : 'text-dimmer'}`}
                >
                  {ready ? t.value : '—'}
                </div>
              </div>
            )
          })}
        </div>
        <div className="scroll-dark max-h-[330px] overflow-auto rounded-md bg-ink px-3 py-[11px]">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[.07em] text-dim">
            Execution log
          </div>
          {shownLog.map((l, i) => (
            <div
              key={i}
              className="whitespace-pre-wrap font-mono text-[11px] leading-[1.65]"
              style={{ color: l.color }}
            >
              {l.text}
            </div>
          ))}
          {stagesDone === 0 && (
            <div className="font-mono text-[11px] leading-[1.65] text-dim">
              No stages executed yet.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
