import { createRoot } from 'react-dom/client'
import { mockIPC } from '@tauri-apps/api/mocks'
import { ReportScreen } from '../src/screens/ReportScreen'
import { useApp } from '../src/store'
import type { CaseData } from '../src/lib/backend'

const calls: { command: string; payload: Record<string, unknown> }[] = []
let previewCounter = 0
Object.assign(globalThis, { isTauri: true, reportCalls: calls })
mockIPC((command, args) => {
  if (command === 'pick_export_path') return 'C:/exports/report.pdf'
  if (command !== 'backend_request') throw new Error(`Unexpected native command ${command}`)
  const payload = args?.payload as Record<string, unknown>
  const method = String(args?.command)
  calls.push({ command: method, payload })
  if (method === 'get_export_sections') return [
    ...[['case_details', 'Case details'], ['evidence', 'Evidence inventory'],
      ['hashes', 'SHA-256 hashes'], ['tools', 'Utility versions and commands'],
      ['integrity', 'Page-integrity results'], ['schemas', 'Schema mappings'],
      ['timeline', 'Transaction timeline'], ['histories', 'Record histories'],
      ['reconciliation', 'Reconciliation results'], ['gaps', 'Evidence gaps and limitations'],
      ['provenance', 'Provenance references'], ['notes', 'Examiner notes']].map(([id, title]) => ({
        id, title, optional: false, dependencies: [], default_profiles: ['investigator', 'full'],
      })),
    ...[['exact_matches', 'Exact comparison details'], ['physical_records', 'All extracted physical records'],
      ['binlog_events', 'All decoded binlog events'], ['complete_timeline', 'Complete transaction timeline'],
      ['complete_histories', 'Complete record histories'], ['complete_schemas', 'Complete schema mappings'],
      ['intermediate_analysis', 'Complete intermediate analysis']].map(([id, title]) => ({
        id, title, optional: true, dependencies: [], default_profiles: ['full'],
      })),
  ]
  if (method === 'preview_export') {
    previewCounter++
    return { preview_token: `preview-${previewCounter}`, page: 1, pages: 2,
      format: payload.format, redacted: payload.redacted,
      profile: payload.profile, json_size_bytes: 2048, counts: {},
      selection: { sections: payload.sections, automatic_sections: [], partial: true },
      lines: ['FORENSIC EXAMINATION REPORT', payload.redacted ? '[VALUE-001]' : 'Sensitive original',
        ...(payload.sections as string[]).map(id => `SECTION: ${id}`)] }
  }
  if (method === 'export_preview_page') return { preview_token: payload.preview_token,
    page: payload.page, pages: 2, format: 'PDF', redacted: true, profile: 'investigator',
    json_size_bytes: 2048, counts: {}, selection: { sections: ['case_details'], automatic_sections: [], partial: true },
    lines: ['SECOND REPORT PAGE'] }
  if (method === 'export_case') return { path: payload.path }
  if (method === 'get_case_data') return { case: { case_id: 'browser-case' }, tables: {
    reports: [{ report_id: 'browser-case:pdf:v1', format: 'pdf', version: 1,
      actor_id: '1', actor_username: 'Examiner', created_at: '2026-10-11T12:00:00+00:00' }],
  } }
  throw new Error(`Unexpected backend command ${method}`)
})
useApp.setState({ data: { case: { case_id: 'browser-case' } } as CaseData,
  pipelineComplete: true, busy: false, reportFormat: 'PDF' })
createRoot(document.getElementById('root')!).render(<ReportScreen />)
