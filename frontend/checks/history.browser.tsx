import { createRoot } from 'react-dom/client'
import { mockIPC } from '@tauri-apps/api/mocks'
import { RecordHistoryScreen } from '../src/screens/RecordHistoryScreen'
import { useApp } from '../src/store'
import type { CaseData, HistoryPageItem } from '../src/lib/backend'

const calls: string[] = []
let longHistories = false
let measuredMode = ''
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
  calls.push(name)
  if (name === 'get_history_tables') return { tables: [{ database: 'credit', table: 'credit.accounts', count: 205 }, { database: 'other', table: 'other.accounts', count: 2 }], total: 207 }
  if (name === 'locate_history_record') return { table: 'credit.accounts', offset: 100 }
  if (name !== 'get_history_page' || payload.include_details !== true) throw new Error('Detail requests are forbidden')
  if (measuredMode) return (await fetch(`/measured-${measuredMode}.json`)).json()
  const offset = Number(payload.offset)
  const table = String(payload.table || 'credit.accounts')
  await new Promise(resolve => setTimeout(resolve, table === 'other.accounts' ? 120 : 15))
  const total = table === 'other.accounts' ? 2 : 205
  // Match the real IPC boundary rather than sharing mock objects with React.
  return JSON.parse(JSON.stringify({ items: Array.from({ length: Math.min(100, total - offset) }, (_, i) => item(offset + i, table)), total, offset, limit: 100 }))
})
useApp.setState({ data, selectedRecord: '', recordNavigation: 0 })
createRoot(document.getElementById('root')!).render(<RecordHistoryScreen />)
const waitFor = async (condition: () => boolean) => {
  const started = Date.now()
  while (!condition()) { if (Date.now() - started > 5000) throw new Error('Timed out: ' + document.body.textContent + ' Calls: ' + calls.join(',')); await new Promise(resolve => setTimeout(resolve, 20)) }
}
const assert = (value: unknown, message: string) => { if (!value) throw new Error(message) }
const records = () => [...document.querySelectorAll<HTMLButtonElement>('button[aria-pressed]')]
const filter = (value: string) => { const select = document.querySelector('select')!; select.value = value; select.dispatchEvent(new Event('change', { bubbles: true })) }
Object.assign(window, { runHistoryChecks: async () => {
  await waitFor(() => records().length === 100)
  const before = calls.length
  records()[1].click()
  await waitFor(() => records()[1].getAttribute('aria-pressed') === 'true')
  assert(calls.length === before, 'Selection requested backend data')
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
  useApp.setState({ data: { ...data, case: { ...data.case, case_id: 'history-b' } }, recordNavigation: 0, selectedRecord: '' })
  await waitFor(() => useApp.getState().selectedRecord === 'accounts:0')
  const refreshCalls = calls.length
  useApp.setState({ data: { ...useApp.getState().data! } })
  await waitFor(() => calls.length > refreshCalls && records().length === 100 && !document.body.textContent!.includes('Loading histories'))
  assert(!calls.includes('get_analysis_detail'), 'Lazy detail request was made')
  return 'PASS: bundled page selection, filtering, pagination, stale responses, record navigation, case switching and analysis refresh.'
} })
Object.assign(window, { loadLongHistoryPage: async () => {
  longHistories = true
  useApp.setState({ data: { ...useApp.getState().data! } })
  await waitFor(() => records().length === 100 && document.body.textContent!.includes('400 steps'))
  return new TextEncoder().encode(JSON.stringify(Array.from({ length: 100 }, (_, i) => item(i)))).length
} })
Object.assign(window, { loadMeasuredHistoryPage: async (mode: string) => {
  measuredMode = mode
  useApp.getState().selectRecord('')
  useApp.setState({ data: { ...useApp.getState().data! } })
  await waitFor(() => records().length === 100 && useApp.getState().selectedRecord !== '')
  return true
} })
