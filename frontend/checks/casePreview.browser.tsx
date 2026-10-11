import React from 'react'
import { createRoot } from 'react-dom/client'
import { mockIPC, mockWindows } from '@tauri-apps/api/mocks'
import App from '../src/App'
import { useApp } from '../src/store'
import { CasePreviewController } from '../src/lib/casePreviewController'
import { defaultPreferences, type CaseData, type CasePreview, type CaseSummary } from '../src/lib/backend'

const cases: CaseSummary[] = Array.from({ length: 20 }, (_, n) => ({ id: `case-${n}`, name: `Case ${n}`, examiner: 'Examiner', workspace: '/workspace', opened: `2026-10-${20 - n}`, files: 1, status: 'Registered' }))
const calls: string[] = []
const savedNotes = new Map<string, string>()
let fullDelay = 100, previewDelay = 10, failFull = false, failPreview = true
let active = 0, maximum = 0, lateFull: (() => void) | undefined
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
const preview = (id: string): CasePreview => ({
  case: { case_id: id, case_name: `Case ${id.split('-')[1]}`, examiner: 'Examiner', examiner_notes: savedNotes.get(id) ?? 'Saved notes', workspace_path: '/workspace', created_at: '2026-10-11' },
  evidence: [{ evidence_id: 'evidence', filename: `${id}.ibd`, kind: 'ibd', size_bytes: 100, source_sha256: 'sha256', verification_status: 'verified' }], run: null,
  pipeline: { metrics: { evidence: 1, verified: 1, tables: null, transactions: null, records: null, exact: null, unresolved: null, gaps: null }, summaries: {}, warnings: {} },
})
const full = (id: string): CaseData => ({ case: preview(id).case, run: null, tables: { evidence_files: preview(id).evidence }, analysis: {}, findings: [] })
Object.assign(globalThis, { isTauri: true })
mockWindows('main')
mockIPC(async (command, args) => {
  if (command !== 'backend_request') throw new Error(`Unexpected ${command}`)
  const payload = (args?.payload ?? {}) as Record<string, unknown>
  const name = String(args?.command), id = String(payload.case_id)
  if (['auth_touch', 'auth_lock', 'auth_logout'].includes(name)) return {}
  if (name === 'auth_status') return { user: useApp.getState().user, locked: useApp.getState().locked }
  if (name === 'list_cases') return cases
  if (name === 'get_settings') return useApp.getState().settings
  if (name === 'save_case_notes') { savedNotes.set(id, String(payload.notes)); return full(id) }
  if (name === 'get_case_preview' || name === 'get_case_data') {
    active++; maximum = Math.max(maximum, active); calls.push(`${name}:${id}`)
    try {
      if (name === 'get_case_preview') {
        await wait(previewDelay)
        if (id === 'case-19' && failPreview) { failPreview = false; throw new Error('Preview unavailable') }
        return preview(id)
      }
      if (id === 'case-0') assert(document.body.textContent?.includes('Registered evidence'), 'Preview must paint before full request dispatch')
      if (id === 'late') await new Promise<void>(resolve => { lateFull = resolve })
      else await wait(fullDelay)
      if (failFull) { failFull = false; throw new Error('Full unavailable') }
      return full(id)
    } finally { active-- }
  }
  throw new Error(`Unexpected ${name}`)
}, { shouldMockEvents: true })
useApp.setState({ user: { username: 'Examiner' }, authChecked: true, ready: true, cases, screen: 'cases',
  settings: { workspace: '/workspace', preferences: defaultPreferences, tools: { innochecksum_path: '', ibd2sdi_path: '', ibd2sql_path: '', mysqlbinlog_path: '', python_path: '', include_deleted: false } } })
createRoot(document.getElementById('root')!).render(<App />)
function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message) }
async function until(condition: () => boolean) {
  const start = Date.now()
  while (!condition()) { if (Date.now() - start > 5000) throw new Error(`Timed out: ${document.body.textContent}`); await wait(10) }
}
function button(text: string) {
  const element = [...document.querySelectorAll('button')].find(b => b.textContent?.trim() === text)
  assert(element, `Missing ${text}`); return element
}
Object.assign(window, { runCasePreviewChecks: async () => {
  await until(() => calls.filter(c => c.startsWith('get_case_preview')).length === 20 && active === 0)
  assert(calls.slice(0, 20).every((call, n) => call === `get_case_preview:case-${n}`), 'Newest-created order')
  assert(!calls.some(c => c.startsWith('get_case_data')), 'Unopened cases must not load full data')
  const start = performance.now()
  button('View').click()
  assert(useApp.getState().screen === 'intake', 'View switches immediately')
  assert(!useApp.getState().busy, 'Background work must not set busy')
  await until(() => !!document.querySelector('#case-details-heading'))
  const cachedClickMs = performance.now() - start
  previewDelay = 60; fullDelay = 300
  const textarea = document.querySelector('textarea')!
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Unsaved edits')
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
  await until(() => useApp.getState().data !== null)
  assert(document.querySelector('textarea')?.value === 'Unsaved edits', 'Full loading preserves unsaved notes')
  assert(useApp.getState().screen === 'intake', 'Full loading preserves screen')
  button('Save notes').click()
  await until(() => !useApp.getState().busy && useApp.getState().data?.case.examiner_notes === 'Unsaved edits')
  assert(document.querySelector('textarea')?.value === 'Unsaved edits', 'Notes mutation refresh preserves editor')
  failFull = true
  void useApp.getState().openCase('case-1')
  button('Pipeline').click()
  await until(() => !!document.querySelector('#pipeline-heading'))
  assert(!useApp.getState().data, 'Pipeline displays before full data')
  assert(document.body.textContent?.includes('Evidence files'), 'Pipeline scalar metrics')
  button('Transactions').click()
  await until(() => document.body.textContent!.includes('Loading case analysis'))
  await until(() => !!useApp.getState().analysisError)
  assert(document.body.textContent?.includes('Full unavailable'), 'Analysis error boundary')
  button('Retry analysis').click()
  await until(() => useApp.getState().data?.case.case_id === 'case-1')
  assert(useApp.getState().screen === 'timeline', 'Retry does not change screen')
  void useApp.getState().openCase('case-19')
  await until(() => useApp.getState().data?.case.case_id === 'case-19')
  assert(calls.filter(c => c === 'get_case_preview:case-19').length === 2, 'Failed background preview retried on View')
  void useApp.getState().openCase('unknown')
  await wait(0)
  assert(useApp.getState().screen === 'intake' && !useApp.getState().preview, 'Uncached View has loading layout')
  void useApp.getState().openCase('case-2')
  await until(() => useApp.getState().data?.case.case_id === 'case-2')
  assert(!calls.includes('get_case_data:unknown'), 'Obsolete selected full work skipped')
  void useApp.getState().openCase('late')
  await until(() => !!lateFull)
  await useApp.getState().lockSession()
  lateFull!(); await wait(100)
  assert(useApp.getState().preview === null && useApp.getState().data === null, 'Late response cannot repopulate locked session')
  assert(maximum === 1, 'Preview/full queue is sequential')
  useApp.setState({ locked: false })
  await useApp.getState().signOut()
  assert(!useApp.getState().user && !useApp.getState().preview && !useApp.getState().data, 'Sign-out releases selected data')
  return { cached_click_to_evidence_ms: Math.round(cachedClickMs), cases_prefetched: 20, max_in_flight: maximum }
} })

let memoryController: CasePreviewController | undefined
Object.assign(window, { loadPreviewMemory: async () => {
  memoryController = new CasePreviewController(async <T,>(_command: string, payload: Record<string, unknown>) => {
    const result = await (await fetch('/measured-preview.json')).json() as CasePreview
    result.case.case_id = String(payload.case_id)
    return result as T
  })
  memoryController.prefetch(cases.map(c => c.id))
  await memoryController.preview('case-19')
  return { retained_cases: cases.length }
} })
