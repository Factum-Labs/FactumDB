/** Correlation graph regression fixtures; application screens use backend data. */
import type { CorrelationEdge, RecordRef, ReconRow, Transaction } from '../src/data/types'

export const records: RecordRef[] = [
  { id: 'accounts:101', table: 'finance.accounts', key: 'account_id = 101', pk: '101', label: 'finance.accounts · 101' },
  { id: 'accounts:205', table: 'finance.accounts', key: 'account_id = 205', pk: '205', label: 'finance.accounts · 205' },
  { id: 'accounts:310', table: 'finance.accounts', key: 'account_id = 310', pk: '310', label: 'finance.accounts · 310' },
  { id: 'transfers:9001', table: 'finance.transfers', key: 'transfer_id = 9001', pk: '9001', label: 'finance.transfers · 9001' },
  { id: 'transfers:9002', table: 'finance.transfers', key: 'transfer_id = 9002', pk: '9002', label: 'finance.transfers · 9002' },
]

export const transactions: Transaction[] = [
  { id: 'TX-1452', status: 'Committed', summary: '2 balance updates, 1 insert', when: 'binlog.000020 · 03:14:07', binlogFile: 'binlog.000020', binlogPos: 3980 },
  { id: 'TX-1451', status: 'Committed', summary: '1 status update on transfers', when: 'binlog.000020 · 03:11:52', binlogFile: 'binlog.000020', binlogPos: 3120 },
  { id: 'TX-1449', status: 'Rolled back', summary: '1 update, 1 delete, no commit marker', when: 'binlog.000018 · 02:58:31', binlogFile: 'binlog.000018', binlogPos: 2210 },
  { id: 'TX-1448', status: 'Incomplete', summary: 'BEGIN without terminator in range', when: 'binlog.000018 · 02:41:09', binlogFile: 'binlog.000018', binlogPos: 1180 },
]

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
