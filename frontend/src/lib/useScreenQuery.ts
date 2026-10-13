import { useEffect, useRef, useState } from 'react'
import { useApp } from '../store'
import type { Screen } from '../data/types'
import { request, type CaseData, type Row } from './backend'
import { warmReports } from './reportWarmup'
import { ScreenCache } from './screenCache'
import { ObsoleteRequest } from './requestLane'
import { requestLane } from './requestLane'

export interface ScreenPage<T = Row> { items: T[]; total: number; offset: number; limit: number; summaries?: Record<string, Row> }
export const screenCache = new ScreenCache()
const readyTables = new Set<string>()
const dependencyWarmups = new Map<string, Promise<unknown>>()
function warmDependencies() {
  // Imports are process-wide, so keep them queued across case/revision changes.
  const valid = () => {
    const state = useApp.getState()
    return !!state.user && !state.locked && !!state.data
  }
  for (const kind of ['report', 'analysis', 'pdf']) {
    if (dependencyWarmups.has(kind)) continue
    const pending = request('warm_dependencies', { kind }, { background: true, priority: 3, valid })
    dependencyWarmups.set(kind, pending)
    void pending.catch(() => {
      if (dependencyWarmups.get(kind) === pending) dependencyWarmups.delete(kind)
    })
  }
}
const mainTables: Partial<Record<Screen, string[]>> = {
  timeline: ['transactions'], record: ['histories'], recon: ['reconciliation'],
  gaps: ['finding_groups', 'warning_groups'], prov: ['tool_runs'], report: ['reports'],
}
function readinessKey(opening: number, revision: string, screen: Screen, kind: string) {
  return JSON.stringify([opening, revision, screen, kind])
}

/** Warm bounded first pages after the visible table and its adjacent page. */
export function useCaseWarmup() {
  const caseId = useApp(s => s.activeCaseId)
  const revision = useApp(s => s.preview?.revision ?? s.data?.run?.run_id ?? '')
  const opening = useApp(s => s.caseOpening)
  const screen = useApp(s => s.screen)
  const enabled = useApp(s => !!s.user && !s.locked && !!s.data)
  const reportsEnabled = useApp(s => s.pipelineComplete && !s.busy)
  useEffect(() => {
    if (!enabled || !caseId) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const valid = () => {
      const state = useApp.getState()
      return !!state.user && !state.locked && state.activeCaseId === caseId && state.caseOpening === opening
        && (state.preview?.revision ?? state.data?.run?.run_id ?? '') === revision
    }
    const prepare = () => {
      if (!alive || !valid()) return
      // Navigation's foreground query must finish before adding speculative work.
      if (!(mainTables[screen] ?? []).every(kind => readyTables.has(readinessKey(opening, revision, screen, kind)))) {
        timer = setTimeout(prepare, 50)
        return
      }
      timer = setTimeout(() => {
        if (!alive || !valid()) return
        for (const kinds of Object.values(mainTables)) for (const kind of kinds) {
          const payload = { case_id: caseId, kind, offset: 0, limit: 100 }
          const key = JSON.stringify([JSON.stringify(['get_screen_page', stable(payload)]), revision])
          if (screenCache.fresh(key)) continue
          // Valid across navigation so an existing queued fetch can be promoted.
          void screenCache.load(key, () => request('get_screen_page', payload,
            { background: true, priority: 2, valid, key })).catch(() => {})
        }
        warmDependencies()
        if (reportsEnabled) warmReports(caseId, revision, () => valid() && useApp.getState().pipelineComplete)
      }, 150)
    }
    timer = setTimeout(prepare, 0)
    return () => { alive = false; clearTimeout(timer) }
  }, [enabled, reportsEnabled, caseId, revision, opening, screen])
}
function stable(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item)
}
useApp.subscribe((state, previous) => {
  if (state.caseOpening !== previous.caseOpening || state.preview?.revision !== previous.preview?.revision) readyTables.clear()
  if (state.locked || !state.user || state.user.username !== previous.user?.username) { screenCache.clear(); readyTables.clear() }
})

/** Keep the same page visible across revision changes; never reuse another filter or case. */
export function useScreenQuery<T>(command: string, payload: Record<string, unknown>, screen: Screen, enabled = true) {
  const caseId = useApp(s => s.activeCaseId ?? s.data?.case.case_id)
  const revision = useApp(s => s.preview?.revision ?? s.data?.run?.run_id ?? '')
  const active = useApp(s => s.screen === screen && !s.locked && !!s.user)
  const opening = useApp(s => s.caseOpening)
  const body = stable({ ...payload, case_id: caseId })
  const identity = JSON.stringify([command, body])
  const key = JSON.stringify([identity, revision])
  const cached = screenCache.peek<T>(key)
  const [shown, setShown] = useState<{ identity: string; value: T }>()
  const [error, setError] = useState('')
  const [attempt, retry] = useState(0)
  const handledAttempt=useRef(0)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!caseId || !active || !enabled) return
    let alive = true
    const valid = () => alive && useApp.getState().caseOpening === opening && !useApp.getState().locked
    const available = screenCache.peek<T>(key)
    const markReady = () => {
      if (command === 'get_screen_page' && mainTables[screen]?.includes(String(payload.kind)))
        readyTables.add(readinessKey(opening, revision, screen, String(payload.kind)))
    }
    const force=attempt!==handledAttempt.current
    handledAttempt.current=attempt
    if (available) { setShown({ identity, value: available }); markReady() }
    setError('')
    if (available && screenCache.fresh(key) && !force) { setLoading(false); return () => { alive = false } }
    setLoading(true)
    requestLane.promote(key)
    void screenCache.load(key, () => request<T>(command, JSON.parse(body), { valid, key, background: command === 'get_screen_context' && (screen === 'timeline' || screen === 'record') })).then(value => {
      if (valid()) { setShown({ identity, value }); markReady() }
    }).catch(e => {
      if (valid() && e instanceof ObsoleteRequest) retry(n => n + 1)
      else if (valid()) {
        markReady()
        setError(String(e))
        if (String(e).includes('AuthenticationRequiredError:')) useApp.getState().setError(e)
      }
    }).finally(() => { if (valid()) setLoading(false) })
    return () => { alive = false }
  }, [caseId, active, opening, enabled, key, identity, command, body, attempt, screen, revision, payload.kind])
  const value = enabled ? cached ?? (shown?.identity === identity ? shown.value : undefined) : undefined
  return { value, loading: enabled && (!value || loading), error, retry: () => retry(n => n + 1) }
}

export function useScreenContext(screen: Screen) {
  const base = useApp(s => s.data)
  const context = useScreenQuery<{ tables: CaseData['tables'] }>('get_screen_context', { kind: screen }, screen)
  return { data: base ? { ...base, tables: { ...base.tables, ...context.value?.tables } } : null, ...context }
}

export function useNextPage(page: {total:number;offset:number;limit:number;items?:unknown[]} | undefined, payload: Record<string, unknown>, screen: Screen) {
  const caseId = useApp(s => s.activeCaseId ?? s.data?.case.case_id)
  const revision = useApp(s => s.preview?.revision ?? s.data?.run?.run_id ?? '')
  const opening = useApp(s => s.caseOpening)
  const active = useApp(s => s.screen === screen && !s.locked && !!s.user)
  const body = JSON.stringify(payload)
  useEffect(() => {
    if (!active || !caseId || !page) return
    let alive = true
    const valid = () => useApp.getState().caseOpening === opening && useApp.getState().screen === screen && !useApp.getState().locked && (useApp.getState().preview?.revision ?? useApp.getState().data?.run?.run_id ?? '') === revision
    const timer = setTimeout(() => {
      if (!alive) return
      const prefetch = async () => {
        if (page.offset + page.limit < page.total) {
          const next = { ...JSON.parse(body), case_id: caseId, offset: page.offset + page.limit, limit: page.limit }
          const key = JSON.stringify([JSON.stringify(['get_screen_page', stable(next)]), revision])
          if (!screenCache.peek(key)) await screenCache.load(key, () => request('get_screen_page', next, { background: true, valid, key }))
        }

      }
      void prefetch().catch(()=>{})
    }, 100)
    return () => { alive = false; clearTimeout(timer) }
  }, [active, caseId, revision, opening, page, body, screen])
}
