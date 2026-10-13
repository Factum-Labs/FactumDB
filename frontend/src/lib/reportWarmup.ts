import { useSyncExternalStore } from 'react'
import { request } from './backend'
import { useApp } from '../store'

type Entry = { ready: boolean; at: number }
const entries = new Map<string, Entry>()
const listeners = new Set<() => void>()
let version = 0
const notify = () => { version++; for (const listener of listeners) listener() }
const keyFor = (caseId: string, revision: string, format: string) => JSON.stringify([caseId, revision, format])
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export function useReportWarmupVersion() { return useSyncExternalStore(subscribe, () => version) }
export function backgroundReportReady(caseId: string, revision: string, format: string) {
  const entry = entries.get(keyFor(caseId, revision, format))
  return !!entry?.ready && Date.now() - entry.at < 9 * 60_000
}

/** One small preparation batch per lowest-priority IPC job; bytes stay on disk. */
export function warmReports(caseId: string, revision: string, valid: () => boolean) {
  for (const format of ['PDF', 'JSON']) {
    const key = keyFor(caseId, revision, format)
    const existing = entries.get(key)
    if (existing && (!existing.ready || Date.now() - existing.at < 9 * 60_000)) continue
    const entry = { ready: false, at: Date.now() }
    entries.set(key, entry)
    void (async () => {
      try {
        while (valid() && entries.get(key) === entry) {
          const result = await request<{ preparation_token?: string; preview_token?: string; stage?: string }>(
            'prepare_background_report', { case_id: caseId, format },
            { background: true, priority: 4, valid })
          if (!valid() || entries.get(key) !== entry) return
          if (result.preview_token) { entry.ready = true; entry.at = Date.now(); notify(); return }
          if (result.stage === 'foreground') {
            if (entries.get(key) === entry) entries.delete(key)
            return
          }
          if (!result.preparation_token) throw new Error('Invalid background report preparation')
        }
      } catch { if (entries.get(key) === entry) entries.delete(key) }
    })()
  }
}

export function refreshBackgroundReports(caseId: string, revision: string) {
  for (const format of ['PDF', 'JSON']) entries.delete(keyFor(caseId, revision, format))
  notify()
  warmReports(caseId, revision, () => {
    const state = useApp.getState()
    return !!state.user && !state.locked && state.pipelineComplete &&
      (state.activeCaseId ?? state.data?.case.case_id) === caseId &&
      (state.preview?.revision ?? state.data?.run?.run_id ?? '') === revision
  })
}

useApp.subscribe((state, previous) => {
  if (state.caseOpening !== previous.caseOpening && state.activeCaseId === previous.activeCaseId &&
      state.preview?.revision === previous.preview?.revision && state.user && !state.locked &&
      state.user.username === previous.user?.username && state.pipelineComplete) {
    // Preserve finished previews and let a new opening resume unfinished backend slots.
    for (const [key, entry] of entries) if (!entry.ready) entries.delete(key)
    notify()
    return
  }
  if (state.locked || !state.user || state.user.username !== previous.user?.username ||
      state.caseOpening !== previous.caseOpening || state.preview?.revision !== previous.preview?.revision ||
      !state.pipelineComplete && previous.pipelineComplete) {
    entries.clear(); notify()
    const caseId = previous.activeCaseId
    if (caseId && state.user && !state.locked && state.user.username === previous.user?.username)
      void request('cancel_background_reports', { case_id: caseId }).catch(() => {})
  }
})
