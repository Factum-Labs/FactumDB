import { createRoot } from 'react-dom/client'
import { mockIPC } from '@tauri-apps/api/mocks'
import { RecordHistoryScreen } from '../src/screens/RecordHistoryScreen'
import { useApp } from '../src/store'
import type { CaseData, HistoryPageItem } from '../src/lib/backend'

const calls: string[] = []
const pageCalls: { table: string; offset: number; caseId: string }[] = []
const completed: { table: string; offset: number; caseId: string }[] = []
let activePages = 0
let maximumActivePages = 0
let initialPrefetchAfterDisplay = false
let failNextPrefetch = false
let prefetchFailed = false
let longHistories = false
let measuredMode = ''
let holdAdjacent = false
const adjacentWaiters: (() => void)[] = []
const measuredCompleted = new Set<number>()
const measuredLatency: number[] = []
let measurementEpoch = 0
const data: CaseData = { case: { case_id: 'history-a', case_name: 'Test', examiner: 'Test', workspace_path: '', created_at: '' }, tables: {}, analysis: { reconstruction: { details_deferred: true, history_count: 205 } }, findings: [], run: null }
function item(index: number, table = 'credit.accounts'): HistoryPageItem {
  const record = { id: `accounts:${index}`, database: table.split('.')[0], table, key: index, label: `Account ${index}` }
  const steps = longHistories ? Array.from({ length: 400 }, (_, step) => ({ kind: 'gap', rule_id: 'R-HIST-009', description: `${index}-${step}: ${'x'.repeat(700)}` })) : []
  return { summary: { record, method: 'primary_key_exact', step_count: steps.length }, detail: { record, method: 'primary_key_exact', steps, events: [], committed_state: { marker: `detail-${index}` }, speculative_state: {} }, findings: [] }
}
Object.assign(globalThis, { isTauri: true })
mockIPC(async (command, args) => {
  if (command !== 'backend_request') throw new Error('Unexpected native command')
  const name = String(args?.command)
  const payload = args?.payload as Record<string, unknown>
  const measurement = measurementEpoch
  calls.push(name)
  if (name === 'get_history_tables') return { tables: [{ database: 'credit', table: 'credit.accounts', count: 205 }, { database: 'other', table: 'other.accounts', count: 2 }], total: 207 }
  if (name === 'locate_history_record') return { table: 'credit.accounts', offset: 100 }
  if (name !== 'get_history_page' || payload.include_details !== true) throw new Error('Detail requests are forbidden')
  const offset = Number(payload.offset)
  const table = String(payload.table || 'credit.accounts')
  const call = { table, offset, caseId: String(payload.case_id) }
  if (pageCalls.length === 1 && offset === 100) initialPrefetchAfterDisplay = records().length === 100
  pageCalls.push(call)
  activePages++; maximumActivePages = Math.max(maximumActivePages, activePages)
  if (holdAdjacent && offset > 0) await new Promise<void>(resolve => adjacentWaiters.push(resolve))
  if (measuredMode) {
    const started = performance.now()
    const response = await (await fetch(`/measured-${measuredMode}.json?offset=${offset}`)).json()
    measuredLatency.push(performance.now() - started)
    activePages--; if (measurement === measurementEpoch) measuredCompleted.add(offset)
    return response
  }
  await new Promise(resolve => setTimeout(resolve, table === 'other.accounts' ? 120 : 40))
  activePages--
  if (failNextPrefetch && offset === 100) { failNextPrefetch = false; prefetchFailed = true; throw new Error('Prefetch failed') }
  const total = table === 'other.accounts' ? 2 : longHistories ? 405 : 205
  completed.push(call)
  // Match the real IPC boundary rather than sharing mock objects with React.
  const response = JSON.parse(JSON.stringify({ items: Array.from({ length: Math.min(100, total - offset) }, (_, i) => item(offset + i, table)), total, offset, limit: 100 }))
  if (longHistories && measurement === measurementEpoch) measuredCompleted.add(offset)
  return response
})
useApp.setState({ data, selectedRecord: '', recordNavigation: 0, screen: 'record' })
export default function Fixture() {
  const screen = useApp(state => state.screen)
  const locked = useApp(state => state.locked)
  return locked ? <p>Locked</p> : screen === 'record' ? <RecordHistoryScreen /> : <p>Other screen</p>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
const waitFor = async (condition: () => boolean) => {
  const started = Date.now()
  while (!condition()) { if (Date.now() - started > 5000) throw new Error('Timed out: ' + document.body.textContent + ' Calls: ' + calls.join(',')); await new Promise(resolve => setTimeout(resolve, 20)) }
}
const assert = (value: unknown, message: string) => { if (!value) throw new Error(message) }
const records = () => [...document.querySelectorAll<HTMLButtonElement>('button[aria-pressed]')]
const filter = (value: string) => { const select = document.querySelector('select')!; select.value = value; select.dispatchEvent(new Event('change', { bubbles: true })) }
Object.assign(window, { runHistoryChecks: async () => {
  await waitFor(() => records().length === 100)
  await waitFor(() => completed.some(c => c.offset === 100))
  assert(initialPrefetchAfterDisplay, 'Prefetch started before the first page displayed')
  const before = calls.length
  records()[1].click()
  await waitFor(() => records()[1].getAttribute('aria-pressed') === 'true')
  assert(calls.length === before, 'Selection requested backend data')
  const initialPages = pageCalls.length
  let started = performance.now()
  const button = (text: string) => [...document.querySelectorAll('button')].find(b => b.textContent?.trim() === text)!
  button('Next').click()
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:100' && records().length === 100)
  const cachedNavigationMs = performance.now() - started
  assert(pageCalls.filter(c => c.offset === 100).length === 1, 'Cached next page was fetched again')
  await waitFor(() => completed.some(c => c.offset === 200))
  button('Next').click()
  await waitFor(() => records().length === 5)
  button('Previous').click()
  await waitFor(() => records().length === 100 && useApp.getState().selectedRecord === 'accounts:100')
  assert(pageCalls.filter(c => c.offset === 100).length === 1, 'Previous page was fetched again')
  assert(pageCalls.length >= initialPages + 1, 'Next adjacent page was not prefetched')
  await waitFor(() => completed.filter(c => c.offset === 0).length === 2)
  button('Previous').click()
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:0')
  filter('credit.accounts')
  await waitFor(() => records().length === 100)
  const next = [...document.querySelectorAll('button')].find(b => b.textContent?.trim() === 'Next')!
  next.click()
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:100')
  filter('other.accounts')
  await new Promise(resolve => setTimeout(resolve, 30))
  filter('credit.accounts')
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:0')
  await new Promise(resolve => setTimeout(resolve, 150))
  assert(records().length === 100, 'Stale filter response replaced page')
  filter('other.accounts')
  await waitFor(() => records().length === 2)
  filter('')
  await waitFor(() => records().length === 100)
  useApp.getState().openRecord('accounts:150')
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:150' && records().length === 100 && records()[0].textContent!.includes('100'))
  assert(calls.filter(name => name === 'get_history_tables').length === 1, 'Table options were refetched within one generation')
  useApp.setState({ data: { ...data, case: { ...data.case, case_id: 'history-b' } }, recordNavigation: 0, selectedRecord: '' })
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:0')
  const refreshCalls = calls.length
  useApp.setState({ data: { ...useApp.getState().data! } })
  await waitFor(() => calls.length > refreshCalls && records().length === 100 && !document.body.textContent!.includes('Loading histories'))
  useApp.setState({ locked: true })
  await waitFor(() => document.body.textContent === 'Locked')
  await new Promise(resolve => setTimeout(resolve, 120))
  const lockedCalls = calls.length
  await new Promise(resolve => setTimeout(resolve, 100))
  assert(calls.length === lockedCalls, 'Requests continued while locked')
  useApp.setState({ locked: false })
  await waitFor(() => records().length === 100)
  useApp.setState({ screen: 'settings' })
  await waitFor(() => document.body.textContent === 'Other screen')
  await new Promise(resolve => setTimeout(resolve, 120))
  const leftCalls = calls.length
  await new Promise(resolve => setTimeout(resolve, 100))
  assert(calls.length === leftCalls, 'Requests continued after unmount')
  failNextPrefetch = true
  useApp.setState({ screen: 'record' })
  await waitFor(() => records().length === 100 && prefetchFailed)
  assert(!document.querySelector('[role="alert"]'), 'Background failure surfaced as a foreground error')
  started = pageCalls.filter(c => c.offset === 100).length
  button('Next').click()
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:100' && records().length === 100)
  assert(pageCalls.filter(c => c.offset === 100).length === started + 1, 'Navigation did not retry failed prefetch')
  useApp.setState({ data: null, selectedRecord: '', user: null })
  await waitFor(() => document.body.textContent!.includes('No results available yet'))
  await new Promise(resolve => setTimeout(resolve, 120))
  const signedOutCalls = calls.length
  await new Promise(resolve => setTimeout(resolve, 100))
  assert(calls.length === signedOutCalls, 'Requests continued after sign-out')
  useApp.setState({ data: { ...data }, recordNavigation: 0 })
  await waitFor(() => records().length === 100)
  assert(maximumActivePages === 1, 'Overlapping page requests')
  assert(!calls.includes('get_analysis_detail'), 'Lazy detail request was made')
  return `PASS: cached navigation (${cachedNavigationMs.toFixed(1)} ms), reuse, post-display prefetch, filtering, stale responses, navigation, refresh, lock/unmount and background failure recovery.`
} })
Object.assign(window, { loadLongHistoryPage: async () => {
  const started = performance.now()
  adjacentWaiters.splice(0).forEach(resolve => resolve())
  longHistories = true
  measurementEpoch++; holdAdjacent = true; measuredCompleted.clear()
  filter('')
  useApp.setState({ data: { ...useApp.getState().data! } })
  await waitFor(() => records().length === 100 && document.body.textContent!.includes('400 steps'))
  return { cold_page_ms: performance.now() - started, bytes: new TextEncoder().encode(JSON.stringify(Array.from({ length: 100 }, (_, i) => item(i)))).length }
} })
Object.assign(window, { loadMeasuredHistoryPage: async (mode: string) => {
  const started = performance.now()
  adjacentWaiters.splice(0).forEach(resolve => resolve())
  measuredMode = mode
  measurementEpoch++; holdAdjacent = true; measuredCompleted.clear(); measuredLatency.length = 0
  filter('')
  useApp.getState().selectRecord('')
  useApp.setState({ data: { ...useApp.getState().data! } })
  await waitFor(() => records().length === 100 && useApp.getState().selectedRecord !== '')
  return { cold_page_ms: performance.now() - started }
} })
Object.assign(window, { fillAdjacentHistoryPages: async () => {
  holdAdjacent = false
  adjacentWaiters.splice(0).forEach(resolve => resolve())
  await waitFor(() => measuredCompleted.has(100))
  await new Promise(resolve => setTimeout(resolve, 30))
  const oldSelection = useApp.getState().selectedRecord
  const started = performance.now()
  ;[...document.querySelectorAll('button')].find(b => b.textContent?.trim() === 'Next')!.click()
  await waitFor(() => records().length === 100 && useApp.getState().selectedRecord !== oldSelection && !document.body.textContent!.includes('Loading histories'))
  const cachedNavigationMs = performance.now() - started
  await waitFor(() => measuredCompleted.has(200))
  await new Promise(resolve => setTimeout(resolve, 30))
  return { cached_navigation_ms: cachedNavigationMs, transport_parse_ms: measuredLatency }
} })
