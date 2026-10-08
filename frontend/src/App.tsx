import { useEffect, type FC } from 'react'
import { useApp } from './store'
import type { Screen } from './data/types'
import { A, A_DARK, A_SOFT, GRN } from './lib/tokens'
import { Logo } from './components/Logo'
import { AuthScreen } from './screens/AuthScreen'

import { CasesScreen, IntakeScreen, PipelineScreen, TimelineScreen, RecordHistoryScreen, ReconciliationScreen, GapsScreen, ProvenanceScreen, ReportScreen, SettingsScreen } from './screens/ConnectedScreens'

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

const NAV_GROUPS: { title: string; items: { id: Screen; label: string; code: string }[] }[] = [
  {
    title: 'Case',
    items: [
      { id: 'cases', label: 'Cases', code: 'CS' },
      { id: 'intake', label: 'Evidence', code: 'EV' },
    ],
  },
  {
    title: 'Analysis',
    items: [
      { id: 'pipeline', label: 'Pipeline', code: 'PL' },
      { id: 'timeline', label: 'Transactions', code: 'TX' },
      { id: 'record', label: 'Record history', code: 'RH' },
      { id: 'recon', label: 'Reconciliation', code: 'RC' },
      { id: 'gaps', label: 'Gaps & warnings', code: 'GP' },
      { id: 'prov', label: 'Provenance', code: 'PV' },
    ],
  },
  {
    title: 'Output',
    items: [
      { id: 'report', label: 'Report', code: 'RP' },
      { id: 'settings', label: 'Settings', code: 'ST' },
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
  const user = useApp(s => s.user)
  const signOut = useApp(s => s.signOut)
  const data = useApp(s => s.data)
  const ready = useApp(s => s.ready)
  const busy = useApp(s => s.busy)
  const error = useApp(s => s.error)
  const notice = useApp(s => s.notice)
  const initialize = useApp(s => s.initialize)
  useEffect(() => { void initialize() }, [initialize])
  const screen = useApp((s) => s.screen)
  const go = useApp((s) => s.go)
  const pipelineComplete = useApp((s) => s.pipelineComplete)

  const [title, subtitle] = META[screen]
  const Screen = SCREENS[screen]

  if (!user) return <AuthScreen />

  return (
    <div className="flex h-screen flex-col bg-page text-ink">
      {/* Title bar */}
      <div className="flex h-[34px] flex-none items-center gap-3 border-b border-line bg-chrome px-3">
        <Logo size={26} />
        <div className="h-[14px] w-px bg-line" />
        <div className="flex items-center gap-[7px] text-[11.5px] text-muted">
          <span className="font-mono text-ink">{data?.case.case_id ?? 'FactumDB'}</span>
          <span>{data?.case.case_name ?? 'Select a case'}</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: GRN }} />
          Read-only evidence mode
        </div>
        <div className="h-[14px] w-px bg-line" />
        <div className="text-[11.5px] text-muted">Signed in: {user.username}</div>
        <button disabled={busy} onClick={() => { void signOut() }} className="text-[11.5px] text-accent disabled:opacity-40">Sign out</button>
      </div>

      {/* Top tabs nav */}
      <div className="flex flex-none items-center gap-0.5 overflow-x-auto border-b border-line bg-panel px-2.5">
        {NAV_FLAT.map((n) => {
          const on = screen === n.id
          return (
            <button
              key={n.id}
              disabled={!ready || (busy && n.id === 'cases')}
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

          <div className={'min-h-0 flex-1 overflow-auto px-[18px] pt-4 ' + (screen === 'pipeline' ? 'flex flex-col pb-4' : 'pb-10')}>
            {error && <div role="alert" className="mb-4 whitespace-pre-wrap rounded border border-red-300 bg-red-50 p-3 text-xs text-red-800">{error}{!ready && <button onClick={() => { void initialize() }} className="ml-3 underline">Retry connection</button>}</div>}
            {notice && <div role="status" className="mb-4 rounded border border-green-300 bg-green-50 p-3 text-xs text-green-800">{notice}</div>}
            <div className={screen === 'pipeline' ? 'min-h-0 flex-1' : 'contents'}>
              {ready ? <Screen /> : !error && <p className="text-sm text-muted">Connecting to the Python backend…</p>}
            </div>
          </div>

          {/* Status bar */}
          <div className="flex h-6 flex-none items-center gap-3.5 border-t border-line bg-chrome px-3.5 font-mono text-[10.5px] text-dim">
            <span>{ready ? 'Backend connected · SQLite per case' : 'Backend disconnected'}</span>
            <span>·</span>
            <span>MySQL 8.4.x profile</span>
            <span>·</span>
            <span>hash SHA-256</span>
            <div className="flex-1" />
            <span>{busy ? 'Processing…' : pipelineComplete ? 'Analysis saved' : 'Ready'}</span>
          </div>
        </main>
      </div>
    </div>
  )
}
