import { useEffect, useLayoutEffect, useRef, useState, type FC } from 'react'
import { useApp } from './store'
import type { Screen } from './data/types'
import { A, A_SOFT, GRN } from './lib/tokens'
import { Logo } from './components/Logo'
import { navigationButton } from './components/buttonStyles'
import { AuthScreen } from './screens/AuthScreen'
import { LockedScreen } from './screens/LockedScreen'
import { useSessionLock } from './lib/useSessionLock'

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
  settings: ['Settings', 'Account, preferences and workspace'],
}

const NAV: { id: Screen; label: string }[] = [
  { id: 'cases', label: 'Cases' },
  { id: 'intake', label: 'Evidence' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'timeline', label: 'Transactions' },
  { id: 'record', label: 'Record history' },
  { id: 'recon', label: 'Reconciliation' },
  { id: 'gaps', label: 'Gaps & warnings' },
  { id: 'prov', label: 'Provenance' },
  { id: 'report', label: 'Report' },
  { id: 'settings', label: 'Settings' },
]

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

function CaseScreens({ screen }: { screen: Screen }) {
  const [visited, setVisited] = useState<Screen[]>([screen])
  useEffect(() => { setVisited(items => items.includes(screen) ? items : [...items, screen]) }, [screen])
  return [...new Set([...visited, screen])].map(id => {
    const Component = SCREENS[id]
    return <div key={id} hidden={id !== screen} className={id === 'pipeline' ? 'h-full min-h-0' : undefined}><Component /></div>
  })
}

export default function App() {
  useSessionLock()
  const locked = useApp(s => s.locked)
  const user = useApp(s => s.user)
  const displayName = useApp(s => s.settings?.profile?.display_name)
  const signOut = useApp(s => s.signOut)
  const data = useApp(s => s.data)
  const preview = useApp(s => s.preview)
  const activeCaseId = useApp(s => s.activeCaseId)
  const cases = useApp(s => s.cases)
  const analysisError = useApp(s => s.analysisError)
  const previewError = useApp(s => s.previewError)
  const retryCaseLoading = useApp(s => s.retryCaseLoading)
  const prefetchCases = useApp(s => s.prefetchCases)
  useEffect(() => {
    if (!readyForPrefetch()) return
    let active = true
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => { if (active) prefetchCases() }))
    function readyForPrefetch() { return useApp.getState().ready && !!user && !locked }
    return () => { active = false; cancelAnimationFrame(frame) }
  }, [cases, user, locked, prefetchCases])
  const caseMetadata = preview?.case ?? data?.case
  const listedCase = cases.find(c => c.id === activeCaseId)
  const ready = useApp(s => s.ready)
  const busy = useApp(s => s.busy)
  const error = useApp(s => s.error)
  const notice = useApp(s => s.notice)
  const initialize = useApp(s => s.initialize)
  useEffect(() => { void initialize() }, [initialize])
  const screen = useApp((s) => s.screen)
  const go = useApp((s) => s.go)
  const pipelineComplete = useApp((s) => s.pipelineComplete)
  const opening = useApp(s => s.caseOpening)
  const viewport = useRef<HTMLDivElement>(null)
  const positions = useRef(new Map<string, number>())
  const positionKey = `${opening}:${screen}`
  useLayoutEffect(() => { if (viewport.current) viewport.current.scrollTop = positions.current.get(positionKey) ?? 0 }, [positionKey])
  useEffect(() => { positions.current.clear() }, [opening, locked, user])

  const [title, subtitle] = META[screen]

  if (!user) return <AuthScreen />
  if (locked) return <LockedScreen />

  return (
    <div className="flex h-screen flex-col bg-page text-ink">
      {/* Title bar */}
      <div className="flex h-[34px] flex-none items-center gap-3 border-b border-line bg-chrome px-3">
        <Logo size={26} />
        <div className="h-[14px] w-px bg-line" />
        <div className="flex items-center gap-[7px] text-[11.5px] text-muted">
          <span className="font-mono text-ink">{caseMetadata?.case_id ?? activeCaseId ?? 'FactumDB'}</span>
          <span>{caseMetadata?.case_name ?? listedCase?.name ?? 'Select a case'}</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: GRN }} />
          Read-only evidence mode
        </div>
        <div className="h-[14px] w-px bg-line" />
        <div className="text-[11.5px] text-muted">Signed in: {displayName ? `${displayName} (${user.username})` : user.username}</div>
        <button onClick={() => { void useApp.getState().lockSession() }} className="text-[11.5px] text-accent">Lock</button>
        <button disabled={busy} onClick={() => { void signOut() }} className="text-[11.5px] text-accent disabled:opacity-40">Sign out</button>
      </div>

      {/* Top tabs nav */}
      <div className="flex flex-none items-center gap-0.5 overflow-x-auto border-b border-line bg-panel px-2.5">
        {NAV.map((n) => {
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
            {pipelineComplete && screen !== 'report' && (
              <div className="flex items-center gap-[7px]">
                <button
                  onClick={() => go('report')}
                  className={navigationButton}
                >
                  Export report
                </button>
              </div>
            )}
          </div>

          <div ref={viewport} onScroll={event => { positions.current.set(positionKey, event.currentTarget.scrollTop) }} className={'min-h-0 flex-1 overflow-auto px-[18px] pt-4 ' + (screen === 'pipeline' ? 'flex flex-col pb-4' : 'pb-10')}>
            {error && <div role="alert" className="mb-4 whitespace-pre-wrap rounded border border-red-300 bg-red-50 p-3 text-xs text-red-800">{error}{!ready && <button onClick={() => { void initialize() }} className="ml-3 underline">Retry connection</button>}</div>}
            {activeCaseId && preview && (previewError || analysisError) && ['intake', 'pipeline'].includes(screen) && <div role="alert" className="mb-4 text-xs">{previewError ?? analysisError}<button onClick={retryCaseLoading} className="ml-3 underline">Retry case loading</button></div>}
            {notice && <div role="status" className="mb-4 flex items-center gap-3 rounded border border-green-300 bg-green-50 p-3 text-xs text-green-800">
              <span>{notice}</span><button type="button" aria-label="Dismiss status message" className="ml-auto shrink-0 underline" onClick={() => useApp.setState({ notice: null })}>Dismiss</button>
            </div>}
            <div className={screen === 'pipeline' ? 'min-h-0 flex-1' : 'contents'}>
              {ready ? (activeCaseId && !preview && !data && !['cases', 'settings'].includes(screen)
                  ? <section className="rounded border border-line bg-panel p-4"><p>{listedCase?.name}</p><p>Examiner: {listedCase?.examiner}</p><p role={previewError ? 'alert' : 'status'}>{previewError ?? 'Loading registered evidence and pipeline?'}</p>{previewError && <button onClick={retryCaseLoading}>Retry preview</button>}</section>
                  : <CaseScreens key={opening} screen={screen} />) : !error && <p className="text-sm text-muted">Connecting to the Python backend…</p>}
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
