import { CASE, reportPreview, reportSections } from '../data/caseData'
import { A, A_DARK, PANEL } from '../lib/tokens'
import { useApp } from '../store'

const FORMATS = ['PDF', 'HTML', 'JSON', 'CSV']

export function ReportScreen() {
  const format = useApp((s) => s.reportFormat)
  const setFormat = useApp((s) => s.setFormat)

  return (
    <div className="grid max-w-[1120px] items-start gap-4" style={{ gridTemplateColumns: '330px 1fr' }}>
      <div className="rounded-md border border-line bg-panel px-3.5 py-[13px]">
        <div className="mb-2.5 text-[12px] font-semibold">Format</div>
        <div className="mb-3.5 flex overflow-hidden rounded border border-line-input">
          {FORMATS.map((f) => {
            const on = f === format
            return (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className="h-[28px] flex-1 border-r border-line-input text-[11.5px] last:border-r-0"
                style={{
                  background: on ? A : PANEL,
                  color: on ? '#fff' : '#4e4e4e',
                  fontWeight: on ? 600 : 400,
                }}
              >
                {f}
              </button>
            )
          })}
        </div>

        <div className="mb-2 text-[12px] font-semibold">Sections</div>
        <div className="flex flex-col gap-[5px]">
          {reportSections.map((s) => (
            <label key={s} className="flex cursor-pointer items-center gap-2 text-[12px] text-ink-3">
              <input
                type="checkbox"
                defaultChecked
                className="h-[13px] w-[13px]"
                style={{ accentColor: A }}
              />
              {s}
            </label>
          ))}
        </div>

        <button
          className="mt-3.5 h-[30px] w-full rounded text-[12px] font-medium text-white hover:brightness-110"
          style={{ background: A, border: `1px solid ${A_DARK}` }}
        >
          Generate {format} report
        </button>
      </div>

      <div
        className="rounded-md border border-line bg-panel px-[30px] py-[26px]"
        style={{ boxShadow: '0 1px 3px rgba(0,0,0,.05)' }}
      >
        <div className="text-[10px] font-semibold uppercase tracking-[.09em] text-dim">
          Forensic examination report
        </div>
        <div className="mt-[5px] text-[19px] font-semibold">{CASE.name}</div>
        <div className="mt-[3px] font-mono text-[11.5px] text-muted">
          {CASE.id} · {CASE.examiner} · generated 2026-03-14 11:42 UTC
        </div>
        <div className="my-4 h-px bg-line-mid" />
        {reportPreview.map((p) => (
          <div key={p.h} className="mb-3.5">
            <div className="mb-[5px] text-[11px] font-semibold uppercase tracking-[.05em] text-dim">
              {p.h}
            </div>
            <div className="whitespace-pre-line font-mono text-[12px] leading-[1.6] text-ink-2">
              {p.body}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
