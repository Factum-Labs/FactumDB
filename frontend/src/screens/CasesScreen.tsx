import { Badge } from '../components/Badge'
import { cases } from '../data/caseData'
import { useApp } from '../store'

const GRID = '130px 1fr 110px 92px 108px 140px'

export function CasesScreen() {
  const go = useApp((s) => s.go)
  return (
    <div className="max-w-[1080px]">
      <div className="mb-3.5 flex gap-2.5">
        <button
          onClick={() => go('intake')}
          className="h-[29px] rounded bg-accent px-3 text-[12px] font-medium text-white hover:bg-accent-dark"
        >
          New case
        </button>
        <input
          placeholder="Filter cases…"
          className="h-[29px] w-[230px] rounded border border-line-input bg-panel px-2.5 text-[12px] text-ink outline-none"
        />
      </div>
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div
          className="grid border-b border-line bg-thead px-3 py-[7px] text-[10.5px] font-semibold uppercase tracking-[.07em] text-dim"
          style={{ gridTemplateColumns: GRID }}
        >
          <div>Case ID</div>
          <div>Name</div>
          <div>Examiner</div>
          <div>Evidence</div>
          <div>Status</div>
          <div>Opened</div>
        </div>
        {cases.map((c) => (
          <div
            key={c.id}
            onClick={() => go('intake')}
            className="grid cursor-pointer items-center border-b border-line-soft px-3 py-2 text-[12px] hover:bg-thead"
            style={{ gridTemplateColumns: GRID }}
          >
            <div className="font-mono">{c.id}</div>
            <div>{c.name}</div>
            <div className="text-muted">{c.examiner}</div>
            <div className="text-muted">{c.files} files</div>
            <div>
              <Badge tone={c.tone}>{c.status}</Badge>
            </div>
            <div className="font-mono text-[11.5px] text-muted">{c.opened}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
