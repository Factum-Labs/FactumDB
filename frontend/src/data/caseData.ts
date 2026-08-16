/**
 * Hardcoded demo fixtures for case FDB-2026-014.
 *
 * These stand in for the outputs of the Python sidecar / domain services. The
 * shapes match what TransactionGroupingService, RecordCorrelationService and
 * ReconciliationService are contracted to return, so replacing this module with
 * Tauri command results later is a drop-in swap — no consumer changes.
 */
import type {
  CorrelationEdge,
  RecordRef,
  ReconRow,
  Transaction,
} from './types'
import { A, AMB, GRN } from '../lib/tokens'
import type { BadgeTone } from '../lib/tokens'

export const CASE = {
  id: 'FDB-2026-014',
  name: 'Finance Balance Investigation',
  examiner: 'Analyst 01',
  workspace: '~/factumdb/cases/FDB-2026-014',
  notes: 'Acquired from imaged host FIN-DB-02.',
}

// ── Cases ────────────────────────────────────────────────────────────────────

export const cases: {
  id: string
  name: string
  examiner: string
  files: number
  status: string
  tone: BadgeTone
  opened: string
}[] = [
  { id: 'FDB-2026-014', name: 'Finance Balance Investigation', examiner: 'Analyst 01', files: 5, status: 'Analysed', tone: 'ok', opened: '2026-03-14 09:20' },
  { id: 'FDB-2026-011', name: 'HR Payroll Row Deletions', examiner: 'Analyst 01', files: 3, status: 'Processing', tone: 'info', opened: '2026-03-09 14:02' },
  { id: 'FDB-2026-008', name: 'Vendor Ledger Review', examiner: 'Analyst 04', files: 7, status: 'Gaps found', tone: 'warn', opened: '2026-02-27 10:44' },
  { id: 'FDB-2026-005', name: 'Order Table Consistency', examiner: 'Analyst 02', files: 2, status: 'Analysed', tone: 'ok', opened: '2026-02-18 16:10' },
  { id: 'FDB-2025-097', name: 'Retail Refund Audit', examiner: 'Analyst 04', files: 4, status: 'Archived', tone: 'neutral', opened: '2025-12-02 08:35' },
]

// ── Evidence intake ──────────────────────────────────────────────────────────

export const evidence = [
  { name: 'accounts.ibd', type: 'InnoDB tablespace', size: '112 KB', hash: '9c7f2b41a0e8…e214', state: 'Verified' },
  { name: 'transfers.ibd', type: 'InnoDB tablespace', size: '96 KB', hash: '51ab7cd93f10…a82c', state: 'Verified' },
  { name: 'binlog.000018', type: 'Row binary log', size: '4.1 MB', hash: '0d2e9911cc47…7b03', state: 'Verified' },
  { name: 'binlog.000020', type: 'Row binary log', size: '3.7 MB', hash: '81f42ae0b6d5…35da', state: 'Verified' },
  { name: 'schema_notes.txt', type: 'Examiner note', size: '2 KB', hash: 'a71c04ffe8b2…19c6', state: 'Verified' },
]

// ── Pipeline ─────────────────────────────────────────────────────────────────

export const stages: { name: string; detail: string; time: string; kind: 'ok' | 'warn' }[] = [
  { name: 'Evidence registration', detail: '5 files', time: '0.4 s', kind: 'ok' },
  { name: 'SHA-256 hashing', detail: '5 hashes', time: '2.1 s', kind: 'ok' },
  { name: 'Verified working copies', detail: '5 / 5 match', time: '3.8 s', kind: 'ok' },
  { name: 'InnoDB page validation', detail: '248 pages, 0 damaged', time: '1.6 s', kind: 'ok' },
  { name: 'Schema extraction', detail: '2 tables, 8 columns', time: '0.9 s', kind: 'ok' },
  { name: 'Physical-row extraction', detail: '5 rows', time: '1.2 s', kind: 'ok' },
  { name: 'Binary-log decoding', detail: '2 logs, 1 missing', time: '11.4 s', kind: 'warn' },
  { name: 'Normalization', detail: '412 objects', time: '0.7 s', kind: 'ok' },
  { name: 'Transaction grouping', detail: '4 transactions', time: '0.5 s', kind: 'ok' },
  { name: 'Record correlation', detail: '5 records linked', time: '0.6 s', kind: 'ok' },
  { name: 'State reconstruction', detail: '5 histories', time: '0.4 s', kind: 'ok' },
  { name: 'Reconciliation', detail: '10 comparisons', time: '0.3 s', kind: 'warn' },
  { name: 'Result persistence & report', detail: 'cases.db written', time: '0.8 s', kind: 'ok' },
]

export const stats: { label: string; value: string; color: string }[] = [
  { label: 'Evidence files', value: '5', color: '#1c1b19' },
  { label: 'Verified', value: '5', color: GRN },
  { label: 'Tables parsed', value: '2', color: '#1c1b19' },
  { label: 'Transactions', value: '4', color: '#1c1b19' },
  { label: 'Records correlated', value: '5', color: '#1c1b19' },
  { label: 'Exact matches', value: '3', color: GRN },
  { label: 'Unresolved', value: '3', color: AMB },
  { label: 'Coverage gaps', value: '1', color: AMB },
]

export const logLines: { text: string; color: string }[] = [
  { text: '$ innochecksum --version', color: '#8b8a82' },
  { text: 'innochecksum Ver 8.4.0', color: '#c9c7c0' },
  { text: '$ innochecksum work/accounts.ibd', color: '#8b8a82' },
  { text: '  pages checked: 126   damaged: 0   exit 0', color: '#c9c7c0' },
  { text: '$ ibd2sdi work/accounts.ibd', color: '#8b8a82' },
  { text: '  finance.accounts  @1 account_id  @2 customer_name  @3 balance', color: '#c9c7c0' },
  { text: '$ ibd2sql work/accounts.ibd', color: '#8b8a82' },
  { text: '  3 rows extracted', color: '#c9c7c0' },
  { text: '$ mysqlbinlog --base64-output=DECODE-ROWS -v work/binlog.000020', color: '#8b8a82' },
  { text: '  1 812 events decoded, 6 retained after table filter', color: '#c9c7c0' },
  { text: '! sequence gap: binlog.000019 not present in evidence set', color: 'oklch(0.72 0.13 75)' },
  { text: '  grouping → TX-1452 committed (XID 8821)', color: '#c9c7c0' },
  { text: '  reconciliation → 10 comparisons, 2 conflicting, 3 unresolved', color: 'oklch(0.7 0.16 25)' },
]

// ── Records (RecordCorrelationService identities) ─────────────────────────────

export const records: RecordRef[] = [
  { id: 'accounts:101', table: 'finance.accounts', key: 'account_id = 101', pk: '101', label: 'finance.accounts · 101' },
  { id: 'accounts:205', table: 'finance.accounts', key: 'account_id = 205', pk: '205', label: 'finance.accounts · 205' },
  { id: 'accounts:310', table: 'finance.accounts', key: 'account_id = 310', pk: '310', label: 'finance.accounts · 310' },
  { id: 'transfers:9001', table: 'finance.transfers', key: 'transfer_id = 9001', pk: '9001', label: 'finance.transfers · 9001' },
  { id: 'transfers:9002', table: 'finance.transfers', key: 'transfer_id = 9002', pk: '9002', label: 'finance.transfers · 9002' },
]

// ── Transactions (TransactionGroupingService) ────────────────────────────────

export const transactions: Transaction[] = [
  { id: 'TX-1452', status: 'Committed', summary: '2 balance updates, 1 insert', when: 'binlog.000020 · 03:14:07', binlogFile: 'binlog.000020', binlogPos: 3980 },
  { id: 'TX-1451', status: 'Committed', summary: '1 status update on transfers', when: 'binlog.000020 · 03:11:52', binlogFile: 'binlog.000020', binlogPos: 3120 },
  { id: 'TX-1449', status: 'Rolled back', summary: '1 update, 1 delete, no commit marker', when: 'binlog.000018 · 02:58:31', binlogFile: 'binlog.000018', binlogPos: 2210 },
  { id: 'TX-1448', status: 'Incomplete', summary: 'BEGIN without terminator in range', when: 'binlog.000018 · 02:41:09', binlogFile: 'binlog.000018', binlogPos: 1180 },
]

// ── Correlation edges (RecordCorrelationService) ─────────────────────────────
// Every edge here is a real transaction→record link. The graph renders only
// these; it never infers an edge that the correlation service did not produce.

export const correlationEdges: CorrelationEdge[] = [
  // TX-1448 — incomplete, touches 310 only
  { txId: 'TX-1448', recordId: 'accounts:310', eventType: 'UPDATE' },
  // TX-1449 — rolled back, touches 101 and 9002
  { txId: 'TX-1449', recordId: 'accounts:101', eventType: 'UPDATE' },
  { txId: 'TX-1449', recordId: 'transfers:9002', eventType: 'DELETE' },
  // TX-1451 — committed, touches 9001 only (no flagged record → not in any group)
  { txId: 'TX-1451', recordId: 'transfers:9001', eventType: 'UPDATE' },
  // TX-1452 — committed, touches 101, 205 and 9001
  { txId: 'TX-1452', recordId: 'accounts:101', eventType: 'UPDATE' },
  { txId: 'TX-1452', recordId: 'accounts:205', eventType: 'UPDATE' },
  { txId: 'TX-1452', recordId: 'transfers:9001', eventType: 'INSERT' },
]

// ── Reconciliation (ReconciliationService) ───────────────────────────────────
// Row order here is the order the service emits, which is what the table shows.

export const reconRows: ReconRow[] = [
  { recordId: 'accounts:101', field: 'balance', log: '4000.00', phys: '3500.00', result: 'Conflicting' },
  { recordId: 'accounts:101', field: 'customer_name', log: 'A. Perera', phys: 'A. Perera', result: 'Exact' },
  { recordId: 'accounts:205', field: 'balance', log: '8500.00', phys: 'not observed', result: 'Unresolved' },
  { recordId: 'accounts:205', field: 'customer_name', log: 'B. Silva', phys: 'B. Silva', result: 'Strong' },
  { recordId: 'accounts:310', field: 'balance', log: 'not observed', phys: '2200.00', result: 'Unresolved' },
  { recordId: 'accounts:310', field: 'customer_name', log: 'K. Fernando', phys: 'K. Fernando', result: 'Partial' },
  { recordId: 'transfers:9001', field: 'record presence', log: 'present', phys: 'present', result: 'Exact' },
  { recordId: 'transfers:9001', field: 'amount', log: '1000.00', phys: '1000.00', result: 'Exact' },
  { recordId: 'transfers:9002', field: 'status', log: 'PENDING', phys: 'COMPLETED', result: 'Conflicting' },
  { recordId: 'transfers:9002', field: 'settled_at', log: 'unsupported type', phys: 'unsupported type', result: 'Unsupported' },
]

// ── Transaction detail (timeline screen) ─────────────────────────────────────

export interface TxEventRow {
  pos: string
  col: string
  before: string
  after: string
  changed: boolean
}
export interface TxEvent {
  op: 'INSERT' | 'UPDATE' | 'DELETE'
  table: string
  key: string
  pos: string
  rows: TxEventRow[]
}
export interface TxDetail {
  meta: { k: string; v: string }[]
  events: TxEvent[]
  footer: string
}

export const txDetail: Record<string, TxDetail> = {
  'TX-1452': {
    meta: [
      { k: 'GTID', v: '4f8a:1452' },
      { k: 'XID', v: '8821' },
      { k: 'Source', v: 'binlog.000020' },
      { k: 'Committed', v: '2026-02-11 03:14:07' },
    ],
    footer: 'XID 8821 · COMMIT recorded at binlog.000020 pos 4412',
    events: [
      {
        op: 'UPDATE', table: 'finance.accounts', key: 'account_id=101', pos: 'pos 3980–4102',
        rows: [
          { pos: '@1', col: 'account_id', before: '101', after: '101', changed: false },
          { pos: '@2', col: 'customer_name', before: 'A. Perera', after: 'A. Perera', changed: false },
          { pos: '@3', col: 'balance', before: '5000.00', after: '4000.00', changed: true },
        ],
      },
      {
        op: 'UPDATE', table: 'finance.accounts', key: 'account_id=205', pos: 'pos 4102–4224',
        rows: [
          { pos: '@1', col: 'account_id', before: '205', after: '205', changed: false },
          { pos: '@2', col: 'customer_name', before: 'B. Silva', after: 'B. Silva', changed: false },
          { pos: '@3', col: 'balance', before: '7500.00', after: '8500.00', changed: true },
        ],
      },
      {
        op: 'INSERT', table: 'finance.transfers', key: 'transfer_id=9001', pos: 'pos 4224–4412',
        rows: [
          { pos: '@1', col: 'transfer_id', before: '—', after: '9001', changed: true },
          { pos: '@2', col: 'source_account', before: '—', after: '101', changed: true },
          { pos: '@4', col: 'amount', before: '—', after: '1000.00', changed: true },
          { pos: '@5', col: 'status', before: '—', after: 'COMPLETED', changed: true },
        ],
      },
    ],
  },
  'TX-1451': {
    meta: [
      { k: 'GTID', v: '4f8a:1451' },
      { k: 'XID', v: '8817' },
      { k: 'Source', v: 'binlog.000020' },
      { k: 'Committed', v: '2026-02-11 03:11:52' },
    ],
    footer: 'XID 8817 · COMMIT recorded at binlog.000020 pos 3312',
    events: [
      {
        op: 'UPDATE', table: 'finance.transfers', key: 'transfer_id=9001', pos: 'pos 3120–3312',
        rows: [
          { pos: '@1', col: 'transfer_id', before: '9001', after: '9001', changed: false },
          { pos: '@5', col: 'status', before: 'PENDING', after: 'COMPLETED', changed: true },
        ],
      },
    ],
  },
  'TX-1449': {
    meta: [
      { k: 'GTID', v: '4f8a:1449' },
      { k: 'XID', v: '—' },
      { k: 'Source', v: 'binlog.000018' },
      { k: 'Terminator', v: 'ROLLBACK 02:58:44' },
    ],
    footer: 'ROLLBACK recorded at binlog.000018 pos 2588 · no XID event present',
    events: [
      {
        op: 'UPDATE', table: 'finance.accounts', key: 'account_id=101', pos: 'pos 2210–2402',
        rows: [
          { pos: '@1', col: 'account_id', before: '101', after: '101', changed: false },
          { pos: '@3', col: 'balance', before: '5000.00', after: '3500.00', changed: true },
        ],
      },
      {
        op: 'DELETE', table: 'finance.transfers', key: 'transfer_id=9002', pos: 'pos 2402–2588',
        rows: [
          { pos: '@1', col: 'transfer_id', before: '9002', after: '—', changed: true },
          { pos: '@5', col: 'status', before: 'PENDING', after: '—', changed: true },
        ],
      },
    ],
  },
  'TX-1448': {
    meta: [
      { k: 'GTID', v: '4f8a:1448' },
      { k: 'XID', v: '—' },
      { k: 'Source', v: 'binlog.000018' },
      { k: 'Terminator', v: 'none in range' },
    ],
    footer: 'BEGIN at binlog.000018 pos 1180 · no COMMIT or ROLLBACK before end of imported range',
    events: [
      {
        op: 'UPDATE', table: 'finance.accounts', key: 'account_id=310', pos: 'pos 1180–1372',
        rows: [
          { pos: '@1', col: 'account_id', before: '310', after: '310', changed: false },
          { pos: '@2', col: 'customer_name', before: 'K. Fernando', after: 'K. Fernando', changed: false },
          { pos: '@3', col: 'balance', before: 'not observed', after: 'not observed', changed: false },
        ],
      },
    ],
  },
}

// ── Record history (StateReconstructionService) ──────────────────────────────

export interface HistoryStep {
  title: string
  source: string
  note: string
  color: string
  fields: { col: string; val: string; highlight: boolean }[]
}
export interface RecordHistory {
  title: string
  method: string
  steps: HistoryStep[]
}

export const recordHistory: Record<string, RecordHistory> = {
  'accounts:101': {
    title: 'finance.accounts · account_id = 101',
    method: 'primary-key exact match',
    steps: [
      { title: 'Earliest observed state', source: 'binlog.000018 pos 2210', note: 'First row image available in the imported log set.', color: '#9a998f', fields: [{ col: 'balance', val: '5000.00', highlight: false }, { col: 'customer_name', val: 'A. Perera', highlight: false }] },
      { title: 'TX-1449 · UPDATE (rolled back)', source: 'binlog.000018 pos 2210', note: 'Transaction was rolled back; this change should not be durable.', color: '#9a998f', fields: [{ col: 'balance', val: '5000.00 → 3500.00', highlight: true }] },
      { title: 'TX-1452 · UPDATE', source: 'binlog.000020 pos 3980', note: 'Committed with XID 8821 alongside two further events.', color: A, fields: [{ col: 'balance', val: '5000.00 → 4000.00', highlight: true }, { col: 'customer_name', val: 'unchanged', highlight: false }] },
      { title: 'Physical state in .ibd', source: 'accounts.ibd via ibd2sql', note: 'Physical row holds 3500.00, matching the rolled-back value rather than the committed one.', color: 'oklch(0.55 0.16 25)', fields: [{ col: 'balance', val: '3500.00', highlight: false }, { col: 'result', val: 'Conflicting', highlight: false }] },
    ],
  },
  'accounts:205': {
    title: 'finance.accounts · account_id = 205',
    method: 'primary-key exact match',
    steps: [
      { title: 'Earliest observed state', source: 'binlog.000018 pos 2402', note: 'First row image available in the imported log set.', color: '#9a998f', fields: [{ col: 'balance', val: '7500.00', highlight: false }] },
      { title: 'TX-1452 · UPDATE', source: 'binlog.000020 pos 4102', note: 'Credit recorded in the same committed transaction.', color: A, fields: [{ col: 'balance', val: '7500.00 → 8500.00', highlight: true }] },
      { title: 'Physical state in .ibd', source: 'accounts.ibd via ibd2sql', note: 'Row not present in the extracted page set; no physical value to compare against.', color: 'oklch(0.62 0.15 55)', fields: [{ col: 'balance', val: 'not observed', highlight: false }, { col: 'result', val: 'Unresolved', highlight: false }] },
    ],
  },
  'accounts:310': {
    title: 'finance.accounts · account_id = 310',
    method: 'primary-key exact match',
    steps: [
      { title: 'TX-1448 · UPDATE (incomplete)', source: 'binlog.000018 pos 1180', note: 'BEGIN observed with no terminator in the imported range.', color: '#9a998f', fields: [{ col: 'customer_name', val: 'K. Fernando', highlight: false }] },
      { title: 'Coverage gap', source: 'binlog.000019 absent', note: 'Events between binlog.000018 pos 8814 and binlog.000020 pos 12 cannot be observed.', color: 'oklch(0.62 0.13 75)', fields: [{ col: 'balance', val: 'not observed', highlight: false }] },
      { title: 'Physical state in .ibd', source: 'accounts.ibd via ibd2sql', note: 'Physical row exists but no log-derived value is available to compare.', color: 'oklch(0.62 0.15 55)', fields: [{ col: 'balance', val: '2200.00', highlight: false }, { col: 'result', val: 'Unresolved', highlight: false }] },
    ],
  },
  'transfers:9001': {
    title: 'finance.transfers · transfer_id = 9001',
    method: 'primary-key exact match',
    steps: [
      { title: 'Record absent', source: 'no prior event', note: 'No event referencing this key appears before TX-1452.', color: '#9a998f', fields: [{ col: 'state', val: 'absent', highlight: false }] },
      { title: 'TX-1452 · INSERT', source: 'binlog.000020 pos 4224', note: 'Inserted after both balance updates, within the same commit.', color: A, fields: [{ col: 'amount', val: '1000.00', highlight: true }, { col: 'status', val: 'COMPLETED', highlight: true }] },
      { title: 'Physical state in .ibd', source: 'transfers.ibd via ibd2sql', note: 'Record present with matching values.', color: GRN, fields: [{ col: 'result', val: 'Exact', highlight: false }] },
    ],
  },
  'transfers:9002': {
    title: 'finance.transfers · transfer_id = 9002',
    method: 'primary-key exact match',
    steps: [
      { title: 'Earliest observed state', source: 'binlog.000018 pos 2402', note: 'Row present with status PENDING.', color: '#9a998f', fields: [{ col: 'status', val: 'PENDING', highlight: false }] },
      { title: 'TX-1449 · DELETE (rolled back)', source: 'binlog.000018 pos 2402', note: 'Delete recorded inside a transaction that was rolled back.', color: '#9a998f', fields: [{ col: 'state', val: 'deleted → restored', highlight: true }] },
      { title: 'Physical state in .ibd', source: 'transfers.ibd via ibd2sql', note: 'Physical row holds COMPLETED, a value no observed event produced.', color: 'oklch(0.55 0.16 25)', fields: [{ col: 'status', val: 'COMPLETED', highlight: false }, { col: 'result', val: 'Conflicting', highlight: false }] },
    ],
  },
}

// ── Gaps, provenance, report, settings ───────────────────────────────────────

export const gaps: {
  severity: string
  tone: BadgeTone
  title: string
  code: string
  detail: string
  impact: string
  affects: string
}[] = [
  { severity: 'Warning', tone: 'warn', title: 'Binary-log coverage gap', code: 'GAP-001', detail: 'binlog.000019 is absent from the evidence set. Events between binlog.000018 pos 8814 and binlog.000020 pos 12 cannot be observed.', impact: 'Timeline may be incomplete', affects: 'finance.accounts, finance.transfers' },
  { severity: 'Warning', tone: 'bad', title: 'Physical state disagrees with committed log state', code: 'GAP-005', detail: 'finance.accounts · 101 balance and finance.transfers · 9002 status hold physical values that no committed event in the imported set produces.', impact: 'Conflicting classification', affects: 'accounts:101, transfers:9002' },
  { severity: 'Notice', tone: 'neutral', title: 'Physical snapshot timing unknown', code: 'GAP-002', detail: 'The acquisition time of the .ibd files relative to the last log event is not recorded in the evidence metadata.', impact: 'Comparison window uncertain', affects: 'all tables' },
  { severity: 'Notice', tone: 'neutral', title: 'Deleted-row remnants not recovered', code: 'GAP-003', detail: 'Row remnants in free pages are outside the validated scope of this version.', impact: 'Deletion analysis limited', affects: 'finance.transfers' },
  { severity: 'Info', tone: 'info', title: 'Data types within validated subset', code: 'GAP-004', detail: 'All observed columns use INT, VARCHAR and DECIMAL, which are inside the supported subset.', impact: 'No interpretation limit', affects: '8 columns' },
]

export const provChain = [
  { k: 'Evidence file', v: 'accounts.ibd' },
  { k: 'Original SHA-256', v: '9c7f2b41a0e8f31d77a5c0b9e6421ba3d8f0c15e9a24bb7c0f31e2a6d94ae214' },
  { k: 'Working copy', v: '~/factumdb/cases/FDB-2026-014/work/accounts.ibd (hash match)' },
  { k: 'Utility', v: 'mysqlbinlog Ver 8.4.0 · /usr/bin/mysqlbinlog' },
  { k: 'Command', v: 'mysqlbinlog --base64-output=DECODE-ROWS -v work/binlog.000020' },
  { k: 'Event position', v: 'binlog.000020 · pos 3980–4102 · GTID 4f8a:1452 · XID 8821' },
  { k: 'Schema source', v: 'ibd2sdi → finance.accounts (@3 → balance)' },
  { k: 'Correlation rule', v: 'primary-key exact match (account_id)' },
  { k: 'Reconciliation rule', v: 'R-CONFLICT-02 · comparable field values differ' },
]

export const rawLines: { text: string; color: string }[] = [
  { text: '### UPDATE `finance`.`accounts`', color: '#8b8a82' },
  { text: '### WHERE', color: '#c9c7c0' },
  { text: '###   @1=101 /* INT meta=0 nullable=0 is_null=0 */', color: '#c9c7c0' },
  { text: "###   @2='A. Perera' /* VARSTRING(100) */", color: '#c9c7c0' },
  { text: '###   @3=5000.00 /* DECIMAL(12,2) */', color: '#c9c7c0' },
  { text: '### SET', color: '#c9c7c0' },
  { text: '###   @1=101', color: '#c9c7c0' },
  { text: "###   @2='A. Perera'", color: '#c9c7c0' },
  { text: '###   @3=4000.00', color: 'oklch(0.7 0.11 150)' },
  { text: '--- physical row via ibd2sql: @3=3500.00', color: 'oklch(0.7 0.16 25)' },
]

export const reportSections = [
  'Case details', 'Evidence inventory', 'SHA-256 hashes', 'Utility versions and commands',
  'Page-integrity results', 'Schema mappings', 'Transaction timeline', 'Record histories',
  'Reconciliation results', 'Evidence gaps and limitations', 'Provenance references', 'Examiner notes',
]

export const reportPreview = [
  { h: '2. Evidence inventory', body: 'accounts.ibd      112 KB   9c7f…e214   verified\ntransfers.ibd      96 KB   51ab…a82c   verified\nbinlog.000018     4.1 MB   0d2e…7b03   verified\nbinlog.000020     3.7 MB   81f4…35da   verified' },
  { h: '7. Transaction timeline', body: 'TX-1452  committed  GTID 4f8a:1452  XID 8821\n  UPDATE finance.accounts  101  balance 5000.00 → 4000.00\n  UPDATE finance.accounts  205  balance 7500.00 → 8500.00\n  INSERT finance.transfers 9001 amount 1000.00' },
  { h: '9. Reconciliation results', body: '10 comparisons · 3 exact · 1 strong · 1 partial\n2 conflicting · 2 unresolved · 1 unsupported' },
  { h: '10. Evidence gaps and limitations', body: 'GAP-001  binlog.000019 absent; timeline may be incomplete.\nGAP-005  physical state disagrees with committed log state.\nFactumDB does not attribute changes to a person or determine intent.' },
]

export const tools = [
  { name: 'ibd2sdi', path: '/usr/bin/ibd2sdi', version: '8.4.0', state: 'Detected' },
  { name: 'innochecksum', path: '/usr/bin/innochecksum', version: '8.4.0', state: 'Detected' },
  { name: 'ibd2sql', path: '/opt/ibd2sql/main.py', version: '1.5', state: 'Detected' },
  { name: 'mysqlbinlog', path: '/usr/bin/mysqlbinlog', version: '8.4.0', state: 'Detected' },
]

export const settings = [
  { k: 'Case root', v: '~/factumdb/cases' },
  { k: 'Hash algorithm', v: 'SHA-256 (fixed)' },
  { k: 'Evidence handling', v: 'read-only, working copies verified' },
  { k: 'MySQL profile', v: '8.4.x · InnoDB · file-per-table · row logging' },
]
