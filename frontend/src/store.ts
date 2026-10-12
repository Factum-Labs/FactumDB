import { create } from 'zustand'
import type { Screen } from './data/types'
import { request, type AuthStatus, type CaseData, type CasePreview, type CaseSummary, type PipelineRun, type Settings, type ToolSettings } from './lib/backend'

import { CasePreviewController, afterPaint } from './lib/casePreviewController'

interface AppState {
  activeCaseId: string | null; preview: CasePreview | null; previewLoading: boolean; previewError: string | null
  analysisLoading: boolean; analysisError: string | null
  saveNotes: (notes: string) => Promise<boolean>
  prefetchCases: () => void; retryCaseLoading: () => void; refreshSelected: () => Promise<void>

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
  activeCaseId: null, preview: null, previewLoading: false, previewError: null, analysisLoading: false, analysisError: null,
  locked: false,
  user: null, data: null, cases: [], settings: null, ready: false, screen: 'cases',
  pipelineComplete: false, stagesDone: 0, runningStage: null, cancelRequested: false,
  recordNavigation: 0, selectedRecordTable: '', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [], reportFormat: 'JSON',
  error: null, notice: null,
  tablePages: {},
}
export const useApp = create<AppState>((set, get) => {
  const previews = new CasePreviewController(async <T,>(command: string, payload: Record<string, unknown>) => {
    try { return await request<T>(command, payload) }
    catch (error) {
      if (String(error).includes('AuthenticationRequiredError:')) get().setError(error)
      throw error
    }
  })
  let lockedCaseId: string | null = null
  let sessionGeneration = 0
  let selection = 0
  let loadingToken = -1
  const releaseSelected = () => { selection++; set({ activeCaseId: null, preview: null, data: null, previewLoading: false, previewError: null, analysisLoading: false, analysisError: null, pipelineComplete: false, stagesDone: 0 }) }
  const clearSession = () => { sessionGeneration++; previews.clear(); releaseSelected() }
  const full = (id: string, token: number) => {
    if (get().busy || get().locked || selection !== token || get().activeCaseId !== id) return
    if (loadingToken === token) return
    loadingToken = token
    set({ analysisLoading: true, analysisError: null })
    void previews.full(id, () => selection === token && get().activeCaseId === id && !get().locked && !!get().user).then(data => {
      if (data) { apply(data); set({ analysisLoading: false }) }
    }).catch(error => {
      if (selection === token) { loadingToken = -1; set({ analysisLoading: false, analysisError: String(error) }) }
    })
  }
  const loadSelected = async (fresh: boolean) => {
    const id = get().activeCaseId
    if (!id || get().locked || !get().user) return
    const token = ++selection
    if (fresh) previews.invalidate(id)
    set({ previewLoading: true, previewError: null, analysisLoading: true, analysisError: null, data: null })
    try {
      const preview = await previews.preview(id, true)
      if (!preview || selection !== token || get().activeCaseId !== id) return
      set({ preview, previewLoading: false, pipelineComplete: preview.run?.complete ?? false,
        stagesDone: preview.run?.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length ?? 0 })
      afterPaint(() => full(id, token))
    } catch (error) { if (selection === token) set({ previewLoading: false, previewError: String(error), analysisLoading: false, analysisError: String(error) }) }
  }

  const apply = (data: CaseData) => set({
    data, pipelineComplete: data.run?.complete ?? false,
    stagesDone: data.run?.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length ?? 0,
  })
  const refresh = async (all = false) => {
    if (get().locked) return
    const session = sessionGeneration
    const cases = await request<CaseSummary[]>('list_cases')
    if (session !== sessionGeneration || get().locked || !get().user) return
    if (all) previews.clear()
    set({ cases })
    const id = get().activeCaseId
    if (id && !cases.some(c => c.id === id)) { selection++; previews.invalidate(id); set({ activeCaseId: null, preview: null, data: null, screen: 'cases', analysisLoading: false, previewLoading: false }) }
    await loadSelected(true)
    afterPaint(() => { if (session === sessionGeneration && !get().locked && get().user) previews.prefetch(get().cases.map(c => c.id)) })
  }
  const action = async (work: () => Promise<void>, mutatesCase = false): Promise<boolean> => {
    if (get().busy) return false
    if (mutatesCase && get().activeCaseId) { selection++; previews.invalidate(get().activeCaseId!) }
    set({ busy: true, error: null, notice: null })
    try { await work(); return true }
    catch (error) { get().setError(error); return false }
    finally { set({ busy: false, runningStage: null }); const id = get().activeCaseId; if (id && !get().data && !get().previewError) afterPaint(() => full(id, selection)) }
  }
  const caseId = () => {
    const id = get().activeCaseId ?? get().data?.case.case_id
    if (!id) throw new Error('Open or create a case first.')
    return id
  }
  const execute = async (all: boolean, onDone?: () => void) => {
    await action(async () => {
      set({ cancelRequested: false })
      let run = (get().preview?.run ?? get().data?.run)
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
    }, true)
  }
  return {
    locked: false,
    lockSession: async () => {
      lockedCaseId = get().activeCaseId ?? get().data?.case.case_id ?? null
      clearSession()
      set({ locked: true, error: null, notice: null })
      try { await request('auth_lock') } catch (error) { get().setError(error) }
    },
    unlockSession: password => action(async () => {
      const auth = await request<AuthStatus>('auth_unlock', { password })
      set({ user: auth.user, locked: false, activeCaseId: lockedCaseId })
      const settings = await request<Settings>('get_settings')
      set({ settings, ready: true })
      await refresh()
    }),
    settingsCommand: async <T,>(command: string, payload: Record<string, unknown> = {}, notice?: string) => {
      let result: T | undefined
      await action(async () => {
        result = await request<T>(command, payload)
        if (command === 'configure_profile' || command === 'configure_preferences') set({ settings: result as Settings })
        if (command === 'restore_workspace') clearSession()
        if (command === 'restore_workspace') set({ ...signedOut, notice: `Workspace restored. Rollback copy: ${(result as { rollback_path: string }).rollback_path}. Sign in with an account from the backup.` })
        else if (notice) set({ notice })
      })
      return result
    },
    user: null, authChecked: false,
    tablePages: {},
    setTablePage: (key, page) => set(state => ({ tablePages: { ...state.tablePages, [key]: page } })),
    activeCaseId: null, preview: null, previewLoading: false, previewError: null, analysisLoading: false, analysisError: null,
    prefetchCases: () => { if (get().ready && get().user && !get().locked) previews.prefetch(get().cases.map(c => c.id)) },
    retryCaseLoading: () => { void loadSelected(true) },
    refreshSelected: () => loadSelected(true),
    screen: 'cases', data: null, cases: [], settings: null, busy: false, ready: false, error: null, notice: null,
    pipelineComplete: false, stagesDone: 0, runningStage: null, cancelRequested: false,
    recordNavigation: 0, selectedRecordTable: '', selectedTx: '', selectedRecord: '', selectedTool: '', reportFormat: 'JSON', expandedGroups: [],
    go: screen => { if (!get().busy || screen !== 'cases') set({ screen }) },
    setError: error => {
      const message = error instanceof Error ? error.message : String(error)
      const authentication = message.startsWith('AuthenticationRequiredError:')
      if (authentication) clearSession()
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
      lockedCaseId = null
      clearSession()
      await request('auth_logout')
      set(signedOut)
    }).then(() => {}),
    refresh: () => action(() => refresh(true)).then(() => {}),
    saveNotes: notes => action(async () => {
      await request('save_case_notes', { case_id: caseId(), notes })
      await loadSelected(true)
    }, true),
    openCase: async id => {
      if (get().busy || get().locked) return
      const cached = previews.cached(id)
      selection++
      set({ activeCaseId: id, data: null, preview: cached ?? null, screen: 'intake', previewLoading: !cached,
        previewError: null, analysisLoading: true, analysisError: null, pipelineComplete: cached?.run?.complete ?? false,
        stagesDone: cached?.run?.stages.filter(s => ['succeeded', 'skipped'].includes(s.status)).length ?? 0,
        selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [] })
      // Cached snapshots render first, then revalidate before loading analysis.
      if (cached) { const token = selection; afterPaint(() => { if (selection === token) void loadSelected(true) }) }
      else await loadSelected(false)
    },
    createCase: name => action(async () => {
      const result = await request<{ case_id: string }>('create_case', { case_name: name })
      set({ activeCaseId: result.case_id, preview: null, data: null })
      await refresh()
      set({ screen: 'intake', selectedTx: '', selectedRecord: '', selectedTool: '', expandedGroups: [] })
    }),
    deleteCase: (id, confirmation) => action(async () => {
      await request('delete_case', { case_id: id, confirmation })
      previews.invalidate(id)
      if (get().activeCaseId === id) { releaseSelected(); set({
        data: null, screen: 'cases', pipelineComplete: false, stagesDone: 0,
        runningStage: null, cancelRequested: false, selectedTx: '', selectedRecord: '',
        selectedTool: '', expandedGroups: [], tablePages: {},
      }) }
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
    }, true),
    verifyEvidence: evidence_id => action(async () => {
      try { await request('verify_evidence', { case_id: caseId(), evidence_id }) }
      finally { await refresh() }
    }, true).then(() => {}),
    runStage: () => execute(false),
    runAllStages: onDone => execute(true, onDone),
    cancelPipeline: async () => {
      if (get().busy) { set({ cancelRequested: true }); return }
      await action(async () => {
        const run = (get().preview?.run ?? get().data?.run)
        if (!run || run.stopped) return
        await request('cancel_pipeline', { run_id: run.run_id })
        await request('run_next_stage', { run_id: run.run_id })
        await refresh()
      }, true)
    },
    retryPipeline: () => action(async () => {
      const run = (get().preview?.run ?? get().data?.run)
      if (!run) return
      await request('retry_pipeline', { run_id: run.run_id }); await refresh()
    }, true).then(() => {}),
    resetPipeline: () => action(async () => {
      await request('start_pipeline', { case_id: caseId() }); await refresh()
    }, true).then(() => {}),
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
