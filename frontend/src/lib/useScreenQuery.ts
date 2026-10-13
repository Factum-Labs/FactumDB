import { useEffect, useRef, useState } from 'react'
import { useApp } from '../store'
import type { Screen } from '../data/types'
import { request, type CaseData, type Row } from './backend'
import { ScreenCache } from './screenCache'
import { ObsoleteRequest } from './requestLane'
import { requestLane } from './requestLane'

export interface ScreenPage<T = Row> { items: T[]; total: number; offset: number; limit: number; summaries?: Record<string, Row> }
export const screenCache = new ScreenCache()
function stable(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item)
}
useApp.subscribe((state, previous) => {
  if (state.locked || !state.user || state.user.username !== previous.user?.username) screenCache.clear()
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
    const force=attempt!==handledAttempt.current
    handledAttempt.current=attempt
    if (available) setShown({ identity, value: available })
    setError('')
    if (available && screenCache.fresh(key) && !force) { setLoading(false); return () => { alive = false } }
    setLoading(true)
    requestLane.promote(key)
    void screenCache.load(key, () => request<T>(command, JSON.parse(body), { valid, key, background: command === 'get_screen_context' && (screen === 'timeline' || screen === 'record') })).then(value => {
      if (valid()) setShown({ identity, value })
    }).catch(e => {
      if (valid() && e instanceof ObsoleteRequest) retry(n => n + 1)
      else if (valid()) {
        setError(String(e))
        if (String(e).includes('AuthenticationRequiredError:')) useApp.getState().setError(e)
      }
    }).finally(() => { if (valid()) setLoading(false) })
    return () => { alive = false }
  }, [caseId, active, opening, enabled, key, identity, command, body, attempt, screen])
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
        if (!valid()) return
        const forecast = { timeline: ['record','histories'], record: ['recon','reconciliation'], recon: ['gaps','finding_groups'], gaps: ['timeline','transactions'] }[screen as 'timeline'|'record'|'recon'|'gaps']
        if (!forecast || !useApp.getState().preview?.indexed_screens?.includes(forecast[1])) return
        const next = {case_id:caseId,kind:forecast[1],offset:0,limit:100}
        const key = JSON.stringify([JSON.stringify(['get_screen_page',stable(next)]),revision])
        if (screenCache.peek(key)) return
        const forecastValid = () => useApp.getState().caseOpening===opening && !useApp.getState().locked && [screen,forecast[0]].includes(useApp.getState().screen) && (useApp.getState().preview?.revision ?? '')===revision
        await screenCache.load(key,()=>request('get_screen_page',next,{background:true,valid:forecastValid,key}))
      }
      void prefetch().catch(()=>{})
    }, 100)
    return () => { alive = false; clearTimeout(timer) }
  }, [active, caseId, revision, opening, page, body, screen])
}
