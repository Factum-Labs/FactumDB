import { create } from 'zustand'
import type { Screen } from './data/types'
import { request, type CaseData, type CaseSummary, type PipelineRun, type Settings, type ToolSettings } from './lib/backend'

interface AppState {
  screen: Screen; data: CaseData | null; cases: CaseSummary[]; settings: Settings | null
  busy: boolean; ready: boolean; error: string | null; notice: string | null
  pipelineComplete: boolean; stagesDone: number; runningStage: number | null; cancelRequested: boolean
  selectedTx: string; selectedRecord: string; selectedTool: string; reportFormat: string; expandedGroups: string[]
  go: (screen: Screen) => void
  initialize: () => Promise<void>
  refresh: () => Promise<void>
  openCase: (id: string) => Promise<void>
  createCase: (name: string, examiner: string) => Promise<boolean>
  registerEvidence: (paths: string[]) => Promise<boolean>
  verifyEvidence: (id: string) => Promise<void>
  runStage: () => Promise<void>
  runAllStages: (onDone?: () => void) => Promise<void>
  cancelPipeline: () => Promise<void>
  retryPipeline: () => Promise<void>
  resetPipeline: () => Promise<void>
  configure: (tools: ToolSettings) => Promise<void>
  exportCase: (path: string) => Promise<void>
  setError: (error: unknown) => void
  selectTx: (id: string) => void; selectRecord: (id: string) => void; selectTool: (id: string) => void
  setFormat: (f: string) => void; toggleGroup: (id: string) => void
  openTransaction: (id: string) => void; openRecord: (id: string) => void
}

let initializing: Promise<void> | undefined
export const useApp = create<AppState>((set, get) => {
  const apply = (data: CaseData) => set({
    data, pipelineComplete: data.run?.complete ?? false,
    stagesDone: data.run?.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length ?? 0,
  })
  const refresh = async () => {
    const id = get().data?.case.case_id
    const cases = await request<CaseSummary[]>('list_cases')
    if (id) apply(await request<CaseData>('get_case_data', { case_id: id }))
    set({ cases })
  }
  const action = async (work: () => Promise<void>): Promise<boolean> => {
    if (get().busy) return false
    set({ busy: true, error: null, notice: null })
    try { await work(); return true }
    catch (error) { get().setError(error); return false }
    finally { set({ busy: false, runningStage: null }) }
  }
  const caseId = () => {
    const id = get().data?.case.case_id
    if (!id) throw new Error('Open or create a case first.')
    return id
  }
  const execute = async (all: boolean, onDone?: () => void) => {
    await action(async () => {
      set({ cancelRequested: false })
      let run = get().data?.run
      if (!run) {
        run = await request<PipelineRun>('start_pipeline', { case_id: caseId() })
        await refresh()
      }
      if (run.complete) return
      if (run.stopped) throw new Error('Retry the failed stage or start a new analysis run.')
      do {
        const index = run.stages.findIndex(s => s.status === 'pending')
        set({ runningStage: index < 0 ? null : index })
        run = await request<PipelineRun>('run_next_stage', { run_id: run.run_id })
        // Persisted stage success must reach the UI even if refreshing a view
        // fails. Never leave a completed run looking like a running stage.
        set({ pipelineComplete: run.complete, stagesDone: run.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length,
          runningStage: null, data: get().data ? { ...get().data!, run } : null })
        await refresh()
        if (get().cancelRequested && !run.stopped) {
          await request('cancel_pipeline', { run_id: run.run_id })
          // The orchestrator records cancellation when the next boundary is entered.
          run = await request<PipelineRun>('run_next_stage', { run_id: run.run_id })
          await refresh()
          break
        }
      } while (all && !run.stopped)
      if (run.complete) { set({ notice: 'Analysis complete. Results are saved in the case database.' }); onDone?.() }
      const failed = run.stages.find(s => s.status === 'failed')
      if (failed) get().setError(failed.attempts.at(-1)?.error_message ?? 'Analysis stage failed.')
    })
  }
  return {
    screen: 'cases', data: null, cases: [], settings: null, busy: false, ready: false, error: null, notice: null,
    pipelineComplete: false, stagesDone: 0, runningStage: null, cancelRequested: false,
    selectedTx: '', selectedRecord: '', selectedTool: '', reportFormat: 'JSON', expandedGroups: [],
    go: screen => { if (!get().busy || screen !== 'cases') set({ screen }) },
    setError: error => set({ error: error instanceof Error ? error.message : String(error), notice: null }),
    initialize: () => {
      if (get().ready) return Promise.resolve()
      if (!initializing) initializing = action(async () => {
        const settings = await request<Settings>('get_settings')
        const cases = await request<CaseSummary[]>('list_cases')
        set({ settings, cases, ready: true })
      }).then(() => { initializing = undefined })
      return initializing
    },
    refresh: () => action(refresh).then(() => {}),
    openCase: id => action(async () => {
      apply(await request<CaseData>('get_case_data', { case_id: id }))
      set({ screen: 'intake', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [] })
    }).then(() => {}),
    createCase: (name, examiner) => action(async () => {
      const result = await request<{ case_id: string }>('create_case', { case_name: name, examiner })
      apply(await request<CaseData>('get_case_data', { case_id: result.case_id }))
      await refresh()
      set({ screen: 'intake', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [] })
    }),
    registerEvidence: paths => action(async () => {
      const failures: string[] = []
      for (const source_path of paths) {
        try { await request('register_evidence', { case_id: caseId(), source_path }) }
        catch (error) { failures.push(String(error)) }
      }
      await refresh()
      if (failures.length) throw new Error(failures.join('\n'))
    }),
    verifyEvidence: evidence_id => action(async () => {
      try { await request('verify_evidence', { case_id: caseId(), evidence_id }) }
      finally { await refresh() }
    }).then(() => {}),
    runStage: () => execute(false),
    runAllStages: onDone => execute(true, onDone),
    cancelPipeline: async () => {
      if (get().busy) { set({ cancelRequested: true }); return }
      await action(async () => {
        const run = get().data?.run
        if (!run || run.stopped) return
        await request('cancel_pipeline', { run_id: run.run_id })
        await request('run_next_stage', { run_id: run.run_id })
        await refresh()
      })
    },
    retryPipeline: () => action(async () => {
      const run = get().data?.run
      if (!run) return
      await request('retry_pipeline', { run_id: run.run_id }); await refresh()
    }).then(() => {}),
    resetPipeline: () => action(async () => {
      await request('start_pipeline', { case_id: caseId() }); await refresh()
    }).then(() => {}),
    configure: tools => action(async () => {
      set({ settings: await request<Settings>('configure_settings', { ...tools }), notice: 'Tool settings saved.' })
    }).then(() => {}),
    exportCase: path => action(async () => {
      const result = await request<{ path: string }>('export_case', { case_id: caseId(), format: get().reportFormat, path })
      set({ notice: 'Export saved to ' + result.path })
    }).then(() => {}),
    selectTx: selectedTx => set({ selectedTx }), selectRecord: selectedRecord => set({ selectedRecord }),
    selectTool: selectedTool => set({ selectedTool }), setFormat: reportFormat => set({ reportFormat }),
    toggleGroup: id => set(s => ({ expandedGroups: s.expandedGroups.includes(id) ? s.expandedGroups.filter(g => g !== id) : [...s.expandedGroups, id] })),
    openTransaction: selectedTx => set({ screen: 'timeline', selectedTx }),
    openRecord: selectedRecord => set({ screen: 'record', selectedRecord }),
  }
})
