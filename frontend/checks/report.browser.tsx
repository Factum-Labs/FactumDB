import { createRoot } from 'react-dom/client'
import { mockIPC } from '@tauri-apps/api/mocks'
import { ReportScreen } from '../src/screens/ReportScreen'
import { useApp } from '../src/store'
import type { CaseData } from '../src/lib/backend'

const calls: { command: string; payload: Record<string, unknown> }[] = []
let counter = 0
let pending: Record<string, unknown> | null = null
let polls = 0
Object.assign(globalThis, { isTauri: true, reportCalls: calls })
mockIPC((command, args) => {
  if (command === 'pick_export_path') return 'C:/exports/report.pdf'
  if (command !== 'backend_request') throw new Error(`Unexpected native command ${command}`)
  const payload = args?.payload as Record<string, unknown>
  const method = String(args?.command)
  calls.push({ command: method, payload })
  if (method === 'get_export_definitions') return [
    { format: 'PDF', title: 'Investigator summary PDF', description: 'Grouped findings without individual records.' },
    { format: 'JSON', title: 'Full case JSON', description: 'Every unique observation and complete analysis.' },
  ]
  const fixture = atob((globalThis as unknown as { reportPdfBase64: string }).reportPdfBase64)
  if (method === 'preview_export') {
    counter++; polls = 0
    pending = { preview_token: `preview-${counter}`, page: 1, pages: payload.format === 'PDF' ? 2 : 1,
      format: payload.format, redacted: payload.redacted, detail: payload.format === 'PDF' ? 'summary' : 'full',
      size_bytes: payload.format === 'PDF' ? fixture.length : 2048, counts: { records: 10073 },
      manifest: { case_id: 'browser-case', exported_at: '2026-10-12T00:00:00Z', engine_revision: 2, analysis_format_version: 2 } }
    return { preparation_token: `job-${counter}`, stage: 'starting', processed: 0 }
  }
  if (method === 'export_preview_status') {
    polls++
    if (polls === 1 || (globalThis as unknown as { holdPreparation: boolean }).holdPreparation)
      return { preparation_token: payload.preparation_token, stage: 'reconciliation', processed: 32 }
    return pending
  }
  if (method === 'cancel_export_preview') return { cancelled: true }
  if (method === 'export_preview_page') return { ...pending, page: payload.page }
  if (method === 'export_preview_pdf') return {
    offset: payload.offset, total_bytes: fixture.length,
    data: btoa(fixture.slice(Number(payload.offset), Number(payload.offset) + Number(payload.length))),
  }
  if (method === 'export_case') return { path: payload.path }
  if (method === 'get_case_data') return { case: { case_id: 'browser-case' }, tables: {
    reports: [{ report_id: 'browser-case:pdf:v1', format: 'pdf', version: 1,
      actor_id: '1', actor_username: 'Examiner', created_at: '2026-10-12T12:00:00Z' }],
  } }
  throw new Error(`Unexpected backend command ${method}`)
})
useApp.setState({ data: { case: { case_id: 'browser-case' } } as CaseData,
  pipelineComplete: true, busy: false, reportFormat: 'PDF' })
createRoot(document.getElementById('root')!).render(<ReportScreen />)
