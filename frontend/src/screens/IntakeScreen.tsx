import { Badge } from '../components/Badge'
import { CASE, evidence, missingLogs, NORMALIZATION_STAGE } from '../data/caseData'
import { A, A_DARK } from '../lib/tokens'
import { useApp } from '../store'

const GRID = '190px 92px 78px 1fr 108px'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-muted">
      {label}
      {children}
    </label>
  )
}

const input =
  'h-[29px] rounded border border-line-input bg-panel px-[9px] text-[12px] text-ink outline-none focus:border-accent-light'

export function IntakeScreen() {
  const go = useApp((s) => s.go)
  const stagesDone = useApp((s) => s.stagesDone)
  // Intake registers and hashes files; it does not read what is inside them. The
  // log index is only parsed at normalization, so until that stage has run there
  // is nothing here that can name an absent file (R-COV-001 / R-COV-002).
  const coverageChecked = stagesDone >= NORMALIZATION_STAGE
  const verified = evidence.filter((e) => e.state === 'Verified').length
  return (
    <div className="grid max-w-[1180px] items-start gap-4" style={{ gridTemplateColumns: '320px 1fr' }}>
      <div className="rounded-md border border-line bg-panel p-3.5">
        <div className="mb-3 text-[12px] font-semibold">Case details</div>
        <div className="flex flex-col gap-[11px]">
          <Field label="Case ID">
            <input defaultValue={CASE.id} className={`${input} font-mono`} />
          </Field>
          <Field label="Case name">
            <input defaultValue={CASE.name} className={input} />
          </Field>
          <Field label="Examiner">
            <input defaultValue={CASE.examiner} className={input} />
          </Field>
          <Field label="Case workspace">
            <input defaultValue={CASE.workspace} className={`${input} font-mono text-[11.5px]`} />
          </Field>
          <Field label="Examiner notes">
            <textarea
              rows={3}
              defaultValue={CASE.notes}
              className="resize-y rounded border border-line-input bg-panel px-[9px] py-[7px] text-[12px] text-ink outline-none"
            />
          </Field>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex h-[76px] items-center justify-center gap-2.5 rounded-md border border-dashed border-line-input bg-panel text-[12px] text-muted">
          Drop <span className="font-mono">.ibd</span> files and binary logs here, or
          <button className="h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-page">
            Browse…
          </button>
        </div>

        <div className="overflow-hidden rounded-md border border-line bg-panel">
          <div className="flex items-center gap-2.5 border-b border-line px-3 py-[9px]">
            <div className="text-[12px] font-semibold">Registered evidence</div>
            <div className="text-[11px] text-muted">
              {evidence.length} files · {verified} verified · originals untouched
            </div>
            <div className="flex-1" />
            <button
              onClick={() => go('pipeline')}
              className="h-[26px] rounded px-[11px] text-[11.5px] font-medium text-white hover:brightness-110"
              style={{ background: A, border: `1px solid ${A_DARK}` }}
            >
              Register &amp; verify
            </button>
          </div>
          <div
            className="grid border-b border-line bg-thead px-3 py-[7px] text-[10.5px] font-semibold uppercase tracking-[.07em] text-dim"
            style={{ gridTemplateColumns: GRID }}
          >
            <div>File</div>
            <div>Type</div>
            <div>Size</div>
            <div>SHA-256</div>
            <div>Working copy</div>
          </div>
          {evidence.map((e) => (
            <div
              key={e.name}
              className="grid items-center border-b border-line-soft px-3 py-2 text-[12px]"
              style={{ gridTemplateColumns: GRID }}
            >
              <div className="font-mono">{e.name}</div>
              <div className="text-muted">{e.type}</div>
              <div className="text-muted">{e.size}</div>
              <div className="truncate font-mono text-[11.5px] text-muted">{e.hash}</div>
              <div>
                <Badge tone="ok">{e.state}</Badge>
              </div>
            </div>
          ))}
        </div>

        {coverageChecked && missingLogs.length > 0 && (
          <div
            className="flex items-start gap-[9px] rounded-md px-3 py-2.5"
            style={{ background: 'oklch(0.97 0.03 85)', border: '1px solid oklch(0.88 0.06 85)' }}
          >
            <span
              className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full"
              style={{ background: 'oklch(0.68 0.14 75)' }}
            />
            <div className="text-[11.5px]" style={{ color: '#5c4a20' }}>
              <strong className="font-semibold">
                Binary-log coverage gap (GAP-001 · R-COV-002).
              </strong>{' '}
              <span className="font-mono">mysql-bin.index</span> lists{' '}
              <span className="font-mono">{missingLogs.join(', ')}</span>, which{' '}
              {missingLogs.length === 1 ? 'is' : 'are'} not in this evidence set. Changes recorded
              there cannot be observed, so differences that {missingLogs.length === 1 ? 'file' : 'those files'}{' '}
              could explain are reported as unresolved rather than as conflicts.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
