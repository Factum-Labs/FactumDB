import { create } from 'zustand'
import type { Screen } from './data/types'
import { request, type AuthStatus, type CaseData, type CaseSummary, type PipelineRun, type Settings, type ToolSettings } from './lib/backend'

interface AppState {
  locked: boolean; lockSession: () => Promise<void>; unlockSession: (password: string) => Promise<boolean>
  settingsCommand: <T>(command: string, payload?: Record<string, unknown>, notice?: string) => Promise<T | undefined>
  user: AuthStatus['user']; authChecked: boolean
  authenticate: (username: string, password: string, confirmation?: string) => Promise<boolean>
  signOut: () => Promise<void>
  screen: Screen; data: CaseData | null; cases: CaseSummary[]; settings: Settings | null
  tablePages: Record<string, number>
  setTablePage: (key: string, page: number) => void
  busy: boolean; ready: boolean; error: string | null; notice: string | null
  pipelineComplete: boolean; stagesDone: number; runningStage: number | null; cancelRequested: boolean
  recordNavigation: number; selectedRecordTable: string;
  selectedTx: string; selectedRecord: string; selectedTool: string; reportFormat: string; expandedGroups: string[]
  go: (screen: Screen) => void
  initialize: () => Promise<void>
  refresh: () => Promise<void>
  openCase: (id: string) => Promise<void>
  createCase: (name: string) => Promise<boolean>
  deleteCase: (id: string, confirmation: string) => Promise<boolean>
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
  selectTx: (id: string) => void; selectRecord: (id: string, table?: string) => void; selectTool: (id: string) => void
  setFormat: (f: string) => void; toggleGroup: (id: string) => void
  openTransaction: (id: string) => void; openRecord: (id: string) => void
}

let initializing: Promise<void> | undefined
const signedOut: Partial<AppState> = {
  locked: false,
  user: null, data: null, cases: [], settings: null, ready: false, screen: 'cases',
  pipelineComplete: false, stagesDone: 0, runningStage: null, cancelRequested: false,
  recordNavigation: 0, selectedRecordTable: '', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [], reportFormat: 'JSON',
  error: null, notice: null,
  tablePages: {},
}
export const useApp = create<AppState>((set, get) => {
  const apply = (data: CaseData) => set({
    data, pipelineComplete: data.run?.complete ?? false,
    stagesDone: data.run?.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length ?? 0,
  })
  const refresh = async () => {
    if (get().locked) return
    const id = get().data?.case.case_id
    const cases = await request<CaseSummary[]>('list_cases')
    if (id) {
      const data = await request<CaseData>('get_case_data', { case_id: id })
      if (!get().locked) apply(data)
    }
    if (!get().locked) set({ cases })
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
        if (get().locked) break
        const index = run.stages.findIndex(s => s.status === 'pending')
        set({ runningStage: index < 0 ? null : index })
        run = await request<PipelineRun>('run_next_stage', { run_id: run.run_id })
        // Persisted stage success must reach the UI even if refreshing a view
        // fails. Never leave a completed run looking like a running stage.
        set({ pipelineComplete: run.complete, stagesDone: run.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length,
          runningStage: null, data: get().data ? { ...get().data!, run } : null })
        await refresh()
        if (get().locked) break
        if (get().cancelRequested && !run.stopped) {
          await request('cancel_pipeline', { run_id: run.run_id })
          // The orchestrator records cancellation when the next boundary is entered.
          run = await request<PipelineRun>('run_next_stage', { run_id: run.run_id })
          await refresh()
          break
        }
      } while (all && !run.stopped)
      if (run.complete) { set({ notice: 'Analysis complete. Results are saved in the case database.' }); if (!get().locked) onDone?.() }
      const failed = run.stages.find(s => s.status === 'failed')
      if (failed) get().setError(failed.attempts.at(-1)?.error_message ?? 'Analysis stage failed.')
    })
  }
  return {
    locked: false,
    lockSession: async () => {
      set({ locked: true, error: null, notice: null })
      try { await request('auth_lock') } catch (error) { get().setError(error) }
    },
    unlockSession: password => action(async () => {
      const auth = await request<AuthStatus>('auth_unlock', { password })
      set({ user: auth.user, locked: false })
      const settings = await request<Settings>('get_settings')
      set({ settings, ready: true })
      await refresh()
    }),
    settingsCommand: async <T,>(command: string, payload: Record<string, unknown> = {}, notice?: string) => {
      let result: T | undefined
      await action(async () => {
        result = await request<T>(command, payload)
        if (command === 'configure_profile' || command === 'configure_preferences') set({ settings: result as Settings })
        if (command === 'restore_workspace') set({ ...signedOut, notice: `Workspace restored. Rollback copy: ${(result as { rollback_path: string }).rollback_path}. Sign in with an account from the backup.` })
        else if (notice) set({ notice })
      })
      return result
    },
    user: null, authChecked: false,
    tablePages: {},
    setTablePage: (key, page) => set(state => ({ tablePages: { ...state.tablePages, [key]: page } })),
    screen: 'cases', data: null, cases: [], settings: null, busy: false, ready: false, error: null, notice: null,
    pipelineComplete: false, stagesDone: 0, runningStage: null, cancelRequested: false,
    recordNavigation: 0, selectedRecordTable: '', selectedTx: '', selectedRecord: '', selectedTool: '', reportFormat: 'JSON', expandedGroups: [],
    go: screen => { if (!get().busy || screen !== 'cases') set({ screen }) },
    setError: error => {
      const message = error instanceof Error ? error.message : String(error)
      const authentication = message.startsWith('AuthenticationRequiredError:')
      set({ ...(authentication ? (message.includes('locked') ? { locked: true } : signedOut) : {}), error: message, notice: null })
    },
    initialize: () => {
      if (get().ready) return Promise.resolve()
      if (!initializing) initializing = action(async () => {
        const auth = await request<AuthStatus>('auth_status')
        set({ user: auth.user, authChecked: true, locked: auth.locked ?? false })
        if (auth.locked) return
        if (!auth.user) return
        const [settings, cases] = await Promise.all([request<Settings>('get_settings'), request<CaseSummary[]>('list_cases')])
        set({ settings, cases, ready: true })
      }).then(() => { initializing = undefined })
      return initializing
    },
    authenticate: (username, password, confirmation) => action(async () => {
      const auth = await request<AuthStatus>(confirmation === undefined ? 'auth_login' : 'auth_signup', {
        username, password, ...(confirmation === undefined ? {} : { password_confirmation: confirmation }),
      })
      set({ user: auth.user, authChecked: true })
      const [settings, cases] = await Promise.all([request<Settings>('get_settings'), request<CaseSummary[]>('list_cases')])
      set({ settings, cases, ready: true })
    }),
    signOut: () => action(async () => {
      await request('auth_logout')
      set(signedOut)
    }).then(() => {}),
    refresh: () => action(refresh).then(() => {}),
    openCase: id => action(async () => {
      apply(await request<CaseData>('get_case_data', { case_id: id }))
      set({ screen: 'intake', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [] })
    }).then(() => {}),
    createCase: name => action(async () => {
      const result = await request<{ case_id: string }>('create_case', { case_name: name })
      apply(await request<CaseData>('get_case_data', { case_id: result.case_id }))
      await refresh()
      set({ screen: 'intake', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [] })
    }),
    deleteCase: (id, confirmation) => action(async () => {
      await request('delete_case', { case_id: id, confirmation })
      if (get().data?.case.case_id === id) set({
        data: null, screen: 'cases', pipelineComplete: false, stagesDone: 0,
        runningStage: null, cancelRequested: false, selectedTx: '', selectedRecord: '',
        selectedTool: '', expandedGroups: [], tablePages: {},
      })
      set({ cases: get().cases.filter(item => item.id !== id), notice: 'Case permanently deleted.' })
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
    selectTx: selectedTx => set({ selectedTx }), selectRecord: (selectedRecord, table = '') => set({ selectedRecord, selectedRecordTable: table }),
    selectTool: selectedTool => set({ selectedTool }), setFormat: reportFormat => set({ reportFormat }),
    toggleGroup: id => set(s => ({ expandedGroups: s.expandedGroups.includes(id) ? s.expandedGroups.filter(g => g !== id) : [...s.expandedGroups, id] })),
    openTransaction: selectedTx => set({ screen: 'timeline', selectedTx }),
    openRecord: selectedRecord => set(s => ({ screen: 'record', selectedRecord, selectedRecordTable: '', recordNavigation: s.recordNavigation + 1 })),
  }
})
