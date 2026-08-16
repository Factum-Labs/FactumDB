import type { BadgeTone } from '../lib/tokens'

export type Screen =
  | 'cases'
  | 'intake'
  | 'pipeline'
  | 'timeline'
  | 'record'
  | 'recon'
  | 'gaps'
  | 'prov'
  | 'report'
  | 'settings'

export type ShellMode = 'sidebar' | 'rail' | 'topbar'

export type TxStatus = 'Committed' | 'Rolled back' | 'Incomplete'
export type EventType = 'INSERT' | 'UPDATE' | 'DELETE'

/** Result classes produced by ReconciliationService. */
export type ReconResult =
  | 'Exact'
  | 'Strong'
  | 'Partial'
  | 'Conflicting'
  | 'Unresolved'
  | 'Unsupported'

/** A record identity as produced by RecordCorrelationService. */
export interface RecordRef {
  /** Stable id, e.g. "accounts:101". */
  id: string
  /** Fully-qualified table name, e.g. "finance.accounts". */
  table: string
  /** Primary key rendering, e.g. "account_id = 101". */
  key: string
  /** Primary key value only, used as a canonical sort key. */
  pk: string
  /** Display label used in tables and graph nodes, e.g. "finance.accounts · 101". */
  label: string
}

/** A transaction as produced by TransactionGroupingService. */
export interface Transaction {
  id: string
  status: TxStatus
  summary: string
  when: string
  /** Binlog file the COMMIT (or last event) was observed in — canonical sort key 1. */
  binlogFile: string
  /** Position within that file — canonical sort key 2. */
  binlogPos: number
}

/** A transaction→record edge as produced by RecordCorrelationService. */
export interface CorrelationEdge {
  txId: string
  recordId: string
  eventType: EventType
}

/** One row of the reconciliation table: a per-field classification. */
export interface ReconRow {
  recordId: string
  field: string
  log: string
  phys: string
  result: ReconResult
}

export const RESULT_TONE: Record<ReconResult, BadgeTone> = {
  Exact: 'ok',
  Strong: 'ok',
  Partial: 'warn',
  Conflicting: 'bad',
  Unresolved: 'unresolved',
  Unsupported: 'neutral',
}

export const TX_TONE: Record<TxStatus, BadgeTone> = {
  Committed: 'ok',
  'Rolled back': 'neutral',
  Incomplete: 'warn',
}
