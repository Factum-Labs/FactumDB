import { createRoot } from 'react-dom/client'
import { mockIPC, mockWindows } from '@tauri-apps/api/mocks'
import App from '../src/App'
import { useApp } from '../src/store'
import { screenCache } from '../src/lib/useScreenQuery'
import { defaultPreferences, type CasePreview, type Row } from '../src/lib/backend'

const calls: { command: string; kind: string; offset: number }[] = []
let active = 0, maximum = 0, revision = 'one', failPage = false, savedComplete = false
const reportSteps = new Map<string, number>()
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message) }
const header = (): CasePreview => ({ revision,
  indexed_screens:['transactions','histories','reconciliation','finding_groups'],
  case: { case_id: 'case-a', case_name: 'Progressive case', examiner: 'Examiner', examiner_notes: 'Saved notes', workspace_path: '', created_at: '' },
  evidence: [{ evidence_id: 'file', filename: 'accounts.ibd', kind: 'ibd', verification_status: 'verified' }], run: savedComplete ? { run_id: 'saved-run', case_id: 'case-a', complete: true, stopped: false, cancel_requested: false, stages: [] } : null,
  pipeline: { metrics: { transactions: 205, records: 205, exact: 205 }, summaries: {}, warnings: {} },
})
const transaction = (n: number) => ({ id: `tx-${n}`, status: 'committed', source_file: 'mysql-bin.000001', event_count: 1 })
const history = (n: number) => ({ record: { id: `accounts:${n}`, database: 'credit', table: 'credit.accounts', key: n }, method: 'primary_key_exact', step_count: 0 })
const group = { id: '["R-RECON-002","notice"]', rule: 'R-RECON-002', severity: 'notice', title: 'Coverage limits', explanation: 'Inspect these findings.', service: 'reconciliation', occurrences: 205, subjects: 205, entries: [], toolRunIds: [] }
Object.assign(globalThis, { isTauri: true })
mockWindows('main')
mockIPC(async (command, args) => {
  if (command !== 'backend_request') throw new Error(`Unexpected ${command}`)
  const name = String(args?.command), payload = (args?.payload ?? {}) as Record<string, unknown>
  active++; maximum = Math.max(maximum, active)
  calls.push({ command: name, kind: String(payload.kind ?? (name === 'prepare_background_report' ? payload.format : '') ?? ''), offset: Number(payload.offset ?? 0) })
  try {
    await wait(name === 'get_screen_page' ? 60 : 5)
    if (name === 'cancel_background_reports') return { cancelled: true }
    if (name === 'prepare_background_report') {
      const format = String(payload.format)
      const steps = (reportSteps.get(format) ?? 0) + 1; reportSteps.set(format, steps)
      return steps % 2 ? { preparation_token: `preparing-${format}`, stage: 'rendering', processed: 0 }
        : { preview_token: `ready-${format}` }
    }
    if (name === 'warm_dependencies') return { ready: true }
    if (name === 'get_case_data') throw new Error('Full case loading is forbidden')
    if (name === 'get_case_header') return header()
    if (name === 'auth_status') return { user: useApp.getState().user, locked: useApp.getState().locked }
    if (name === 'list_cases') return useApp.getState().cases
    if (name.startsWith('auth_') || name === 'save_case_notes') return {}
    if (name === 'get_settings') return useApp.getState().settings
    if (name === 'get_screen_context') return { tables: { schemas: [], schema_columns: [], tool_runs: [], reports: [] } }
    if (name === 'get_history_tables') return { tables: [{ database: 'credit', table: 'credit.accounts', count: 205 }], total: 205 }
    if (name === 'get_screen_coverage') return { coverage: { complete: false } }
    if (name === 'get_screen_detail') {
      if (payload.kind === 'transactions') return { detail: { ...transaction(Number(String(payload.identity).split('-')[1])), event_count: 1 }, findings: [] }
      if (payload.kind === 'histories') return { detail: { ...history(Number(String(payload.identity).split(':')[1])), steps: [], events: [], steps_paginated: true }, findings: [] }
      return { detail: { record_id: payload.identity, field: payload.bucket, result: 'Exact' }, findings: [] }
    }
    if (name === 'get_screen_page') {
      if (failPage && payload.kind === 'transactions' && Number(payload.offset ?? 0)===100) { failPage = false; throw new Error('Page unavailable') }
      const offset = Number(payload.offset ?? 0), limit = Number(payload.limit ?? 100)
      let total = 205, items: Row[] = []
      const count = Math.max(0, Math.min(limit, total - offset))
      if (payload.kind === 'transactions') items = Array.from({ length: count }, (_, i) => transaction(offset + i))
      if (payload.kind === 'histories') items = Array.from({ length: count }, (_, i) => history(offset + i))
      if (payload.kind === 'events') { total = 1; items = [] }
      if (payload.kind === 'reconciliation') { total = payload.bucket === 'Conflicting' ? 0 : 205; items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) => ({ record_id: `accounts:${offset+i}`, result: 'Exact', summary: 'Values match', field_count: 1, rule_id: 'R-RECON-001' })) }
      if (payload.kind === 'comparisons') { total = 1; items = [{ record_id: payload.identity, field: 'balance', log_display: '100', phys_display: '100', result: 'Exact' }] }
      if (payload.kind === 'finding_groups') { total = 1; items = [group] as unknown as Row[] }
      if (payload.kind === 'warning_groups') { total = 0; items = [] }
      if (payload.kind === 'findings') items = Array.from({ length: count }, (_, i) => ({ rule_id: group.rule, severity: 'notice', subject: { kind: 'record', id: `accounts:${offset+i}` }, description: `Finding ${offset+i}`, context: {}, provenance: [] }))
      return { items, total, offset, limit, counts: { notice: 1, warning: 0 }, summaries: { reconciliation: { counts: { Exact: 205 } } } }
    }
    throw new Error(`Unexpected ${name}`)
  } finally { active-- }
}, { shouldMockEvents: true })
useApp.setState({ user: { username: 'Examiner' }, ready: true, authChecked: true, screen: 'cases',
  cases: [{ id: 'case-a', name: 'Progressive case', examiner: 'Examiner', workspace: '', opened: '', files: 1, status: 'Complete' }],
  settings: { workspace: '', preferences: defaultPreferences, tools: { innochecksum_path: '', ibd2sdi_path: '', ibd2sql_path: '', mysqlbinlog_path: '', python_path: '', include_deleted: false } },
})
createRoot(document.getElementById('root')!).render(<App />)
const visible = <T extends Element>(selector: string) => [...document.querySelectorAll<T>(selector)].filter(el => !el.closest('[hidden]') && !el.closest('details:not([open])') && el.getClientRects().length > 0)
const button = (label: string) => { const found = visible<HTMLButtonElement>('button').find(el => el.textContent?.replace(/[▴▾▲▼‹›]/g, '').trim() === label); assert(found, `Missing button ${label}`); return found! }
async function until(condition: () => boolean) {
  const start = Date.now()
  while (!condition()) { if (Date.now()-start > 8000) throw new Error('Timed out: '+visible<HTMLElement>('main').map(el=>el.innerText).join('')); await wait(10) }
}
Object.assign(window, { runCasePreviewChecks: async () => {
  await until(() => calls.some(c => c.command === 'get_case_header') && !active)
  const start = performance.now(); button('View').click()
  await until(() => visible('textarea').length === 1)
  const openingMs = performance.now() - start
  const textarea = visible<HTMLTextAreaElement>('textarea')[0]
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Unsaved edits')
  textarea.dispatchEvent(new Event('input', { bubbles: true })); await wait(20)
  const warmKinds = ['transactions','histories','reconciliation','finding_groups','warning_groups','tool_runs','reports']
  await until(() => warmKinds.every(kind => calls.some(c => c.kind === kind && c.offset === 0)) && !active)
  assert(!calls.some(c => c.command === 'get_screen_detail' || ['findings','comparisons','events','steps'].includes(c.kind)), 'Opening warms only main tables, leaving details on demand')
  await until(() => calls.filter(c => c.command === 'warm_dependencies').length === 3 && !active)
  const firstWarm = calls.findIndex(c => c.command === 'warm_dependencies')
  assert(warmKinds.every(kind => calls.findIndex(c => c.command === 'get_screen_page' && c.kind === kind) < firstWarm), 'Dependency imports follow every main-table first page')
  assert(!calls.some(c => c.command === 'prepare_background_report'), 'An incomplete case does not prepare reports')
  useApp.setState({ pipelineComplete: true })
  await until(() => reportSteps.get('PDF') === 2 && reportSteps.get('JSON') === 2 && !active)
  const firstReport = calls.findIndex(c => c.command === 'prepare_background_report')
  assert(calls.filter(c => c.command === 'warm_dependencies').every(c => calls.indexOf(c) < firstReport), 'Reports follow dependency imports after analysis completes')
  const initialTransactions = calls.filter(c => c.command === 'get_screen_page' && c.kind === 'transactions' && c.offset === 0).length
  button('Transactions').click()
  await until(() => visible('button[aria-pressed]').length === 100)
  await until(() => calls.some(c => c.kind === 'transactions' && c.offset === 100) && !active)
  assert(calls.filter(c => c.command === 'get_screen_page' && c.kind === 'transactions' && c.offset === 0).length === initialTransactions, 'First visit reuses its warmed table')
  const before = calls.filter(c => c.kind === 'transactions' && c.offset === 100).length
  assert(calls.some(c=>c.kind==='histories'),'Every main table should be prefetched on opening')
  button('Next').click()
  await until(() => visible<HTMLButtonElement>('button[aria-pressed]')[0]?.textContent?.includes('tx-100') === true)
  assert(calls.filter(c => c.kind === 'transactions' && c.offset === 100).length === before, 'Next page uses its cached response')
  button('Evidence').click(); await wait(30)
  assert(visible<HTMLTextAreaElement>('textarea')[0] === textarea && textarea.value === 'Unsaved edits', 'Navigation preserves the notes editor')
  await useApp.getState().refreshSelected()
  assert(visible<HTMLTextAreaElement>('textarea')[0] === textarea && textarea.value === 'Unsaved edits', 'Refresh preserves unsaved notes')
  const selectedCase = useApp.getState()
  button('Cases').click(); await wait(30)
  assert(useApp.getState().activeCaseId === selectedCase.activeCaseId && useApp.getState().data === selectedCase.data
    && useApp.getState().caseOpening === selectedCase.caseOpening, 'Returning to Cases preserves the selected case and loaded data')
  button('Evidence').click(); await wait(30)
  assert(visible<HTMLTextAreaElement>('textarea')[0] === textarea && textarea.value === 'Unsaved edits', 'Returning through Cases preserves the notes editor')
  button('Reconciliation').click()
  await until(() => visible('tbody tr').length === 100)
  assert(!calls.some(c => c.kind === 'comparisons'), 'Comparisons are deferred')
  button('View comparisons').click()
  await until(() => calls.some(c => c.kind === 'comparisons'))
  await until(() => visible('tbody').length > 1)
  const resultFilter = visible<HTMLSelectElement>('select')[0]
  resultFilter.value='Conflicting';resultFilter.dispatchEvent(new Event('change',{bubbles:true}))
  await until(()=>visible('tbody tr').length===0)
  button('Gaps & warnings').click()
  await until(() => visible('button[aria-expanded]').some(el => el.textContent?.includes('View findings')))
  assert(!calls.some(c => c.kind === 'findings'), 'Finding occurrences are deferred')
  button('View findings').click()
  await until(() => visible('tbody tr').length >= 102)
  button('Next').click()
  await until(() => visible('td').some(el => el.textContent === 'Finding 100'))
  const viewport=document.querySelector<HTMLElement>('main > div.overflow-auto')!
  viewport.scrollTop=600;viewport.dispatchEvent(new Event('scroll'));await wait(20)
  button('Record history').click()
  await until(() => visible('button[aria-pressed]').length === 100)
  button('Gaps & warnings').click();await wait(20)
  assert(viewport.scrollTop===600,'Revisited screens restore their scroll position')
  button('Record history').click();await wait(20)
  button('Reconciliation').click();await wait(20)
  assert(visible<HTMLSelectElement>('select')[0]?.value==='Conflicting','Navigation preserves reconciliation filters')
  button('Transactions').click(); await wait(20)
  assert(visible<HTMLButtonElement>('button[aria-pressed]')[0]?.textContent?.includes('tx-100'), 'Revisited screen keeps its page')
  // A changed revision retains the current page while revalidating it.
  revision = 'two'; failPage = true
  await useApp.getState().refreshSelected(); await wait(20)
  assert(visible('button[aria-pressed]').length === 100, 'Refresh keeps loaded rows visible')
  await until(() => visible('[role=alert]').some(el=>el.textContent?.includes('Page unavailable')))
  button('Retry').click()
  await until(()=>!active && !visible('[role=alert]').length)
  assert(!calls.some(c => c.command === 'get_case_data'), 'No screen triggers a full-case read')
  assert(maximum === 1, 'IPC requests share one lane')
  const previousOpening = useApp.getState().caseOpening
  button('Cases').click(); await wait(30)
  assert(useApp.getState().activeCaseId === 'case-a', 'Cases keeps the old selection until View is clicked')
  button('View').click()
  await until(() => visible('textarea').length === 1 && !active)
  assert(useApp.getState().caseOpening === previousOpening + 1, 'View starts a fresh case view')
  assert(visible<HTMLTextAreaElement>('textarea')[0] !== textarea && visible<HTMLTextAreaElement>('textarea')[0].value === 'Saved notes', 'View replaces the previous case view and its unsaved editor')
  // Reopening an already completed saved case automatically prepares both reports.
  savedComplete = true; revision = 'saved-complete'; reportSteps.clear()
  await useApp.getState().refreshSelected()
  await useApp.getState().openCase('case-a')
  await until(() => reportSteps.get('PDF') === 2 && reportSteps.get('JSON') === 2 && !active)
  assert(useApp.getState().pipelineComplete, 'A completed saved case warms both report formats on opening')
  const preparedCalls = calls.filter(c => c.command === 'prepare_background_report').length
  await useApp.getState().openCase('case-a'); await wait(500)
  assert(calls.filter(c => c.command === 'prepare_background_report').length === preparedCalls, 'Reopening an unchanged completed case reuses its prepared reports')
  await useApp.getState().lockSession()
  assert(screenCache.size().entries === 0 && !useApp.getState().data, 'Lock clears cached evidence')
  return { cached_open_ms: Math.round(openingMs), max_in_flight: maximum, independent_screens: 4, full_case_requests: 0 }
} })
