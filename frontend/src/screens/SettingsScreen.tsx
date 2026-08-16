import { Badge } from '../components/Badge'
import { settings, tools } from '../data/caseData'

export function SettingsScreen() {
  return (
    <div className="flex max-w-[860px] flex-col gap-3">
      <div className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">
          External utilities
        </div>
        {tools.map((t) => (
          <div
            key={t.name}
            className="grid items-center gap-2.5 border-b border-line-soft px-3 py-[9px]"
            style={{ gridTemplateColumns: '130px 1fr 130px 92px' }}
          >
            <div className="font-mono text-[12px]">{t.name}</div>
            <div className="font-mono text-[11.5px] text-muted">{t.path}</div>
            <div className="font-mono text-[11.5px] text-muted">{t.version}</div>
            <div>
              <Badge tone="ok">{t.state}</Badge>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-[11px] rounded-md border border-line bg-panel px-3.5 py-[13px]">
        <div className="text-[12px] font-semibold">Workspace</div>
        {settings.map((s) => (
          <div key={s.k} className="grid items-center gap-3" style={{ gridTemplateColumns: '180px 1fr' }}>
            <div className="text-[11.5px] text-muted">{s.k}</div>
            <div className="font-mono text-[11.5px]">{s.v}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
