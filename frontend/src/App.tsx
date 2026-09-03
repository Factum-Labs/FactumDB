import type { FC } from 'react'
import { useApp } from './store'
import type { Screen } from './data/types'
import { A, A_DARK, A_SOFT, GRN } from './lib/tokens'
import { CASE } from './data/caseData'
import { Logo } from './components/Logo'

import { CasesScreen } from './screens/CasesScreen'
import { IntakeScreen } from './screens/IntakeScreen'
import { PipelineScreen } from './screens/PipelineScreen'
import { TimelineScreen } from './screens/TimelineScreen'
import { RecordHistoryScreen } from './screens/RecordHistoryScreen'
import { ReconciliationScreen } from './screens/ReconciliationScreen'
import { GapsScreen } from './screens/GapsScreen'
import { ProvenanceScreen } from './screens/ProvenanceScreen'
import { ReportScreen } from './screens/ReportScreen'
import { SettingsScreen } from './screens/SettingsScreen'

const META: Record<Screen, [string, string]> = {
  cases: ['Cases', 'Open an existing case or create a new one'],
  intake: ['Evidence intake', 'Register files, hash originals, verify working copies'],
  pipeline: ['Pipeline', 'Stage-by-stage processing under the orchestrator'],
  timeline: ['Transaction timeline', 'Row events grouped into committed transactions'],
  record: ['Record history', 'Chronological reconstruction from correlated events'],
  recon: ['Reconciliation', 'Log-derived state compared with physical .ibd state'],
  gaps: ['Evidence gaps', 'Limitations that constrain the conclusions'],
  prov: ['Provenance', 'Trace a finding back to its source artefact'],
  report: ['Report export', 'Reproducible output for examiner review'],
  settings: ['Settings', 'Utility paths, versions and workspace'],
}

const NAV_GROUPS: { title: string; items: { id: Screen; label: string; code: string; count: string }[] }[] = [
  {
    title: 'Case',
    items: [
      { id: 'cases', label: 'Cases', code: 'CS', count: '5' },
      { id: 'intake', label: 'Evidence', code: 'EV', count: '6' },
    ],
  },
  {
    title: 'Analysis',
    items: [
      { id: 'pipeline', label: 'Pipeline', code: 'PL', count: '13' },
      { id: 'timeline', label: 'Transactions', code: 'TX', count: '4' },
      { id: 'record', label: 'Record history', code: 'RH', count: '5' },
      { id: 'recon', label: 'Reconciliation', code: 'RC', count: '10' },
      { id: 'gaps', label: 'Gaps & warnings', code: 'GP', count: '5' },
      { id: 'prov', label: 'Provenance', code: 'PV', count: '' },
    ],
  },
  {
    title: 'Output',
    items: [
      { id: 'report', label: 'Report', code: 'RP', count: '' },
      { id: 'settings', label: 'Settings', code: 'ST', count: '' },
    ],
  },
]

const NAV_FLAT = NAV_GROUPS.flatMap((g) => g.items)

const SCREENS: Record<Screen, FC> = {
  cases: CasesScreen,
  intake: IntakeScreen,
  pipeline: PipelineScreen,
  timeline: TimelineScreen,
  record: RecordHistoryScreen,
  recon: ReconciliationScreen,
  gaps: GapsScreen,
  prov: ProvenanceScreen,
  report: ReportScreen,
  settings: SettingsScreen,
}

export default function App() {
  const screen = useApp((s) => s.screen)
  const go = useApp((s) => s.go)
  const pipelineComplete = useApp((s) => s.pipelineComplete)

  const [title, subtitle] = META[screen]
  const Screen = SCREENS[screen]

  return (
    <div className="flex h-screen flex-col bg-page text-ink">
      {/* Title bar */}
      <div className="flex h-[34px] flex-none items-center gap-3 border-b border-line bg-chrome px-3">
        <Logo size={26} />
        <div className="h-[14px] w-px bg-line" />
        <div className="flex items-center gap-[7px] text-[11.5px] text-muted">
          <span className="font-mono text-ink">{CASE.id}</span>
          <span>{CASE.name}</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: GRN }} />
          Read-only evidence mode
        </div>
        <div className="h-[14px] w-px bg-line" />
        <div className="text-[11.5px] text-muted">Examiner: {CASE.examiner}</div>
      </div>

      {/* Top tabs nav */}
      <div className="flex flex-none items-center gap-0.5 overflow-x-auto border-b border-line bg-panel px-2.5">
        {NAV_FLAT.map((n) => {
          const on = screen === n.id
          return (
            <button
              key={n.id}
              onClick={() => go(n.id)}
              className="h-[34px] whitespace-nowrap border-b-2 px-[11px] text-[12px] hover:bg-accent-soft"
              style={{
                borderBottomColor: on ? A : 'transparent',
                background: on ? A_SOFT : undefined,
                color: on ? A : '#6e6e6e',
                fontWeight: on ? 600 : 400,
              }}
            >
              {n.label}
            </button>
          )
        })}
      </div>

      <div className="flex min-h-0 flex-1">
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Page header */}
          <div className="flex flex-none items-end gap-3.5 border-b border-line bg-panel px-[18px] pb-[11px] pt-3">
            <div className="min-w-0">
              <div className="text-[15px] font-semibold tracking-[-.005em]">{title}</div>
              <div className="mt-0.5 text-[11.5px] text-muted">{subtitle}</div>
            </div>
            <div className="flex-1" />
            {/* Export is only offered once the pipeline has produced results. */}
            {pipelineComplete && (
              <div className="flex items-center gap-[7px]">
                <button
                  onClick={() => go('report')}
                  className="h-[27px] rounded px-[11px] text-[11.5px] font-medium text-white hover:brightness-110"
                  style={{ background: A, border: `1px solid ${A_DARK}` }}
                >
                  Export report
                </button>
              </div>
            )}
          </div>

          <div className="flex-1 overflow-auto px-[18px] pb-10 pt-4">
            <Screen />
          </div>

          {/* Status bar */}
          <div className="flex h-6 flex-none items-center gap-3.5 border-t border-line bg-chrome px-3.5 font-mono text-[10.5px] text-dim">
            <span>SQLite: cases.db</span>
            <span>·</span>
            <span>MySQL 8.4.x profile</span>
            <span>·</span>
            <span>hash SHA-256</span>
            <div className="flex-1" />
            <span>2 conflicting · 3 unresolved · 1 coverage gap</span>
          </div>
        </main>
      </div>
    </div>
  )
}
