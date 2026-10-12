import { invoke, isTauri } from '@tauri-apps/api/core'

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Row = { [key: string]: Json }
export interface CaseSummary {
  id: string; name: string; examiner: string; workspace: string; opened: string; files: number; status: string
  engine_revision?: number; reanalysis_required?: boolean
}
export interface Attempt {
  number: number; status: string; started_at: string; finished_at: string | null
  item_count: number; error_code: string | null; error_message: string | null; skip_reason: string | null
}
export interface PipelineRun {
  run_id: string; case_id: string; complete: boolean; stopped: boolean; cancel_requested: boolean
  stages: { stage: string; status: string; attempts: Attempt[] }[]
}
export interface CaseData {
  table_counts?: Record<string, number>
  engine_revision?: number; analysis_format_version?: number
  case: { case_id: string; case_name: string; examiner: string; examiner_notes?: string; workspace_path: string; created_at: string; engine_revision?: number; reanalysis_required?: boolean }
  tables: Record<string, Row[]>
  analysis: Record<string, Row>
  findings: Row[]
  finding_rules?: Record<string, { title: string; explanation: string; service: string }>
  run: PipelineRun | null
}
export interface ToolSettings {
  innochecksum_path: string; ibd2sdi_path: string; ibd2sql_path: string
  mysqlbinlog_path: string; python_path: string; include_deleted: boolean
}
export interface Preferences {
  lock_minutes: number; time_mode: 'utc' | 'local' | 'custom'; utc_offset_minutes: number
}
export interface ExaminerProfile { display_name?: string; organization?: string; examiner_id?: string }
export interface Settings { workspace: string; tools: ToolSettings; bundled_tools?: Partial<ToolSettings>; preferences?: Preferences; profile?: ExaminerProfile; workspace_operations_available?: boolean }
export interface AuthStatus { user: { username: string } | null; locked?: boolean }
export interface StorageUsage { total_bytes: number; free_bytes: number; categories: Record<string, number>; cases: Record<string, number> }
export interface BackupPreview { created_at: string; case_count: number; total_bytes: number; sha256: string; original_evidence_included: boolean }
export const defaultPreferences: Preferences = { lock_minutes: 15, time_mode: 'utc', utc_offset_minutes: 0 }

export async function request<T>(command: string, payload: Record<string, unknown> = {}): Promise<T> {
  if (!isTauri()) throw new Error('Open FactumDB in the desktop app to connect to the backend. Run npm run tauri:dev from the project root.')
  return invoke<T>('backend_request', { command, payload })
}
export const pickEvidence = () => invoke<string[]>('pick_evidence')
export const pickExportPath = (format: string) => invoke<string | null>('pick_export_path', { format })
export const pickBackupPath = (restore: boolean) => invoke<string | null>('pick_backup_path', { restore })
export const openWorkspace = () => invoke<void>('open_workspace')

export function rows(value: Json | undefined): Row[] {
  return Array.isArray(value) ? value.filter((r): r is Row => r !== null && typeof r === 'object' && !Array.isArray(r)) : []
}
export function object(value: Json | undefined): Row {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {}
}
export function display(value: Json | undefined): string {
  if (value === undefined) return '—'
  if (value === null) return 'NULL'
  if (typeof value !== 'object') return String(value)
  if (!Array.isArray(value)) {
    if ('__decimal__' in value) return String(value.__decimal__)
    if ('__integer__' in value) return String(value.__integer__)
    if ('__datetime__' in value) return String(value.__datetime__)
    if ('__unobserved__' in value) return '[not observed]'
    if ('__undecodable__' in value) return '[undecodable: ' + String(value.__undecodable__) + ']'
  }
  return JSON.stringify(value)
}

export interface HistoryTables { tables: { database: string; table: string; count: number }[]; total: number }
export interface HistoryPageItem { summary: Row; detail: Row; findings: Row[] }
export interface BundledHistoryPage { items: HistoryPageItem[]; total: number; offset: number; limit: number }
export interface HistoryPage { items: Row[]; total: number; offset: number; limit: number }

export interface CasePreview {
  case: CaseData['case']; evidence: Row[]; run: PipelineRun | null
  pipeline: { metrics: Record<string, Json>; summaries: Record<string, string>; warnings: Record<string, boolean> }
}
