import { useMemo, useState } from 'react'
import { Badge } from '../components/Badge'
import { display, object, rows, type CaseData, type Json, type Row } from '../lib/backend'
import type { BadgeTone } from '../lib/tokens'
import { useApp } from '../store'
import { useAnalysisDetail } from '../lib/useAnalysisDetail'

const button = 'h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-page disabled:cursor-not-allowed disabled:opacity-40'
const statusLabels: Record<string, string> = { committed: 'Committed', rolled_back: 'Rolled back', incomplete: 'Incomplete' }
const statusTones: Record<string, BadgeTone> = { committed: 'ok', rolled_back: 'neutral', incomplete: 'warn' }
const operationTones: Record<string, BadgeTone> = { INSERT: 'ok', UPDATE: 'info', DELETE: 'bad' }

function sourceIds(value: Json | undefined): string[] {
  const references = Array.isArray(value) ? rows(value) : [object(value)]
  return [...new Set(references.map(ref => ref.tool_run_id).filter((id): id is string => typeof id === 'string' && !!id))]
}

function inspect(id: string) {
  useApp.getState().selectTool(id)
  useApp.getState().go('prov')
}

function summary(transaction: Row): string {
  if (transaction.event_count !== undefined) return `${display(transaction.event_count)} row events`
  const counts = new Map<string, number>()
  for (const grouped of rows(transaction.events)) {
    const operation = display(object(grouped.event).event_type)
    counts.set(operation, (counts.get(operation) ?? 0) + 1)
  }
  return [...counts].map(([operation, count]) => `${count} ${operation}`).join(', ') || 'No row events'
}

function EventCard({ grouped, schemas, columns }: { grouped: Row; schemas: Row[]; columns: Row[] }) {
  const event = object(grouped.event)
  const before = object(event.before)
  const after = object(event.after)
  const schemaIds = new Set(schemas.filter(schema => schema.database_name === event.database && schema.table_name === event.table).map(schema => schema.schema_id))
  const schemaColumns = columns.filter(column => schemaIds.has(column.schema_id))
  const fields = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  const positions = new Map(schemaColumns.map(column => [String(column.name), Number(column.position)]))
  fields.sort((a, b) => (positions.get(a) ?? Infinity) - (positions.get(b) ?? Infinity) || a.localeCompare(b))
  const keyColumns = [...new Set(schemaColumns.filter(column => column.is_primary_key === 1 || column.is_primary_key === true).map(column => String(column.name)))]
  const keys = keyColumns.filter(key => key in before || key in after).map(key => {
    const oldValue = display(before[key])
    const newValue = display(after[key])
    return `${key}=${key in before && key in after && oldValue !== newValue ? `${oldValue} → ${newValue}` : key in after ? newValue : oldValue}`
  })
  const sources = sourceIds(grouped.provenance).concat(sourceIds(event.provenance))
  const imageValue = (image: Row, raw: Json | undefined, field: string) => raw == null ? 'No row image' : field in image ? display(image[field]) : '[not observed]'
  return <article className="border-b border-line-soft px-[13px] py-[11px] last:border-b-0">
    <div className="flex flex-wrap items-center gap-[9px]">
      <Badge tone={operationTones[String(event.event_type)] ?? 'neutral'}>{display(event.event_type)}</Badge>
      <span className="break-all font-mono text-[12px]">{display(event.database)}.{display(event.table)}</span>
      {keys.length > 0 && <span className="break-all text-[11px] text-muted">key {keys.join(', ')}</span>}
      <span className="ml-auto font-mono text-[10.5px] text-dimmer">Order {display(grouped.order)} · pos {display(event.log_position)} · row {display(event.row_index)}</span>
    </div>
    <p className="mt-1 break-all font-mono text-[10.5px] text-dimmer">{display(event.source_file)}</p>
    {fields.length > 0 ? <div className="mt-[9px] overflow-auto rounded border border-line-mid">
      <table className="w-full min-w-[420px] table-fixed border-collapse text-left">
        <colgroup><col className="w-[150px]" /><col /><col /></colgroup>
        <thead className="bg-thead text-[10px] uppercase tracking-[.07em] text-dim"><tr>
          {['Column', 'Before', 'After'].map(label => <th key={label} className="border-b border-r border-line-mid px-[9px] py-[5px] font-semibold last:border-r-0">{label}</th>)}
        </tr></thead>
        <tbody>{fields.map(field => {
          const changed = field in after && JSON.stringify(before[field]) !== JSON.stringify(after[field])
          return <tr key={field} className="border-b border-line-mid font-mono text-[11.5px] last:border-b-0">
            <td className="break-words border-r border-line-mid px-[9px] py-[5px]">
              {positions.has(field) && <span className="text-dimmer">@{positions.get(field)} </span>}{field}
            </td>
            <td className="break-words border-r border-line-mid px-[9px] py-[5px] text-muted">{imageValue(before, event.before, field)}</td>
            <td className={'break-words px-[9px] py-[5px] ' + (changed ? 'bg-accent-soft font-medium text-accent' : 'text-muted')}>{imageValue(after, event.after, field)}</td>
          </tr>
        })}</tbody>
      </table>
    </div> : <p className="mt-2 text-[11px] text-muted">No row images available.</p>}
    {[...new Set(sources)].map(id => <button type="button" key={id} className="mt-2 mr-3 text-[11px] text-accent underline" onClick={() => inspect(id)}>Inspect source tool run · {id.slice(0, 8)}</button>)}
  </article>
}

function TransactionDetail({ transaction, data }: { transaction: Row; data: CaseData }) {
  const [eventPage, setEventPage] = useState(0)
  const [showProvenance, setShowProvenance] = useState(false)
  const events = rows(transaction.events)
  const pages = Math.max(1, Math.ceil(events.length / 100))
  const currentPage = Math.min(eventPage, pages - 1)
  const sources = sourceIds(transaction.provenance)
  const metadata = [
    ['GTID', transaction.gtid], ['XID', transaction.xid], ['Source', transaction.source_file], ['Committed', transaction.commit_timestamp],
    ['Start position', transaction.start_position], ['End position', transaction.end_position], ['Synthesised', transaction.synthesised],
  ] as const
  return <div className="min-w-0 space-y-3">
    <section className="rounded-md border border-line bg-panel px-3.5 py-[13px]" aria-label="Selected transaction">
      <div className="flex flex-wrap items-center gap-2.5">
        <h2 className="break-all font-mono text-[15px] font-semibold">{display(transaction.id)}</h2>
        <Badge tone={statusTones[String(transaction.status)] ?? 'neutral'}>{statusLabels[String(transaction.status)] ?? display(transaction.status)}</Badge>
        <button type="button" className={button + ' ml-auto'} onClick={() => {
          if (sources.length === 1) inspect(sources[0])
          else setShowProvenance(!showProvenance)
        }}>Provenance</button>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2.5 xl:grid-cols-4">
        {metadata.map(([label, value]) => <div key={label}>
          <dt className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">{label}</dt>
          <dd className="mt-0.5 break-all font-mono text-[12px]">{display(value)}</dd>
        </div>)}
      </dl>
      {showProvenance && <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
        {sources.length ? sources.map(id => <button type="button" key={id} className={button} onClick={() => inspect(id)}>Inspect source tool run · {id.slice(0, 8)}</button>) : <span className="text-muted">No transaction-level source tool run recorded. Event provenance is shown below.</span>}
      </div>}
    </section>
    {transaction.synthesised === true && <p className="rounded-md border border-line bg-panel px-3 py-2 text-[11px] text-muted">Synthesised grouping: the evidence does not establish these events as one transaction.</p>}
    <section aria-labelledby="transaction-events-heading" className="overflow-hidden rounded-md border border-line bg-panel">
      <h2 id="transaction-events-heading" className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">{transaction.status === 'committed' ? 'Events in commit order' : 'Events in log order'}</h2>
      {events.slice(currentPage * 100, (currentPage + 1) * 100).map((grouped, index) => <EventCard key={`${currentPage}:${index}`} grouped={grouped} schemas={data.tables.schemas ?? []} columns={data.tables.schema_columns ?? []} />)}
      {!events.length && <p className="px-3 py-4 text-[11px] text-muted">No row events available.</p>}
      {pages > 1 && <div className="flex items-center gap-3 border-t border-line px-3 py-2 text-[11px] text-muted">
        <button type="button" className={button} disabled={currentPage === 0} onClick={() => setEventPage(currentPage - 1)}>Previous</button>
        <span>Page {currentPage + 1} of {pages} · {events.length} events</span>
        <button type="button" className={button} disabled={currentPage + 1 === pages} onClick={() => setEventPage(currentPage + 1)}>Next</button>
      </div>}
      <p className="border-t border-line px-[13px] py-[9px] text-[11.5px] text-muted">
        {transaction.status === 'committed' ? 'Committed events contribute to reconstructed state.' : transaction.status === 'rolled_back' ? 'Rolled-back events are retained as evidence and do not contribute to committed state.' : 'No commit was observed; these events do not contribute to committed state.'}
      </p>
    </section>
    <details className="rounded-md border border-line bg-panel p-3 text-[11px]">
      <summary className="cursor-pointer font-medium">Transaction outcome, event images and provenance</summary>
      <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono">{JSON.stringify(transaction, null, 2)}</pre>
    </details>
  </div>
}

export function TimelineScreen() {
  const data = useApp(s => s.data)
  const selected = useApp(s => s.selectedTx)
  const transactions = useMemo(() => rows(data?.analysis.grouping?.transactions), [data?.analysis.grouping?.transactions])
  const currentIndex = Math.max(0, transactions.findIndex(transaction => transaction.id === selected))
  const current = transactions[currentIndex]
  const loaded = useAnalysisDetail(data?.case.case_id, 'transaction', current, data?.analysis.grouping?.details_deferred === true)
  const currentPage = Math.floor(currentIndex / 100)
  const pages = Math.max(1, Math.ceil(transactions.length / 100))
  if (!data || !current) return <div className="rounded-md border border-line bg-panel p-4 text-sm text-muted">No results available yet.</div>
  return <div className="grid max-w-[1240px] items-start gap-4 lg:grid-cols-[268px_minmax(0,1fr)]">
    <section aria-labelledby="transactions-heading" className="min-w-0 overflow-hidden rounded-md border border-line bg-panel">
      <h2 id="transactions-heading" className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">Transactions</h2>
      <div className="max-h-[640px] overflow-auto">
        {transactions.slice(currentPage * 100, (currentPage + 1) * 100).map(transaction => <button type="button" key={String(transaction.id)}
          aria-pressed={transaction.id === current.id} onClick={() => useApp.getState().selectTx(String(transaction.id))}
          className={'block w-full border-b border-l-2 border-line-soft px-3 py-[9px] text-left hover:bg-thead ' +
            (transaction.id === current.id ? 'border-l-accent bg-accent-soft' : 'border-l-transparent bg-panel')}>
          <span className="flex flex-wrap items-center gap-[7px]">
            <span className="break-all font-mono text-[12px] font-medium">{display(transaction.id)}</span>
            <Badge tone={statusTones[String(transaction.status)] ?? 'neutral'}>{statusLabels[String(transaction.status)] ?? display(transaction.status)}</Badge>
          </span>
          <span className="mt-[3px] block text-[11px] text-muted">{summary(transaction)}</span>
          <span className="mt-[3px] block break-all font-mono text-[10.5px] text-dimmer">{display(transaction.source_file)} · {display(transaction.commit_timestamp)}</span>
        </button>)}
      </div>
      {pages > 1 && <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-muted">
        <button type="button" className={button} disabled={currentPage === 0} onClick={() => useApp.getState().selectTx(String(transactions[(currentPage - 1) * 100].id))}>Previous</button>
        <span>{currentPage + 1} / {pages}</span>
        <button type="button" className={button} disabled={currentPage + 1 === pages} onClick={() => useApp.getState().selectTx(String(transactions[(currentPage + 1) * 100].id))}>Next</button>
      </div>}
    </section>
    {loaded.detail ? <TransactionDetail key={`${data.case.case_id}:${current.id}`} transaction={loaded.detail} data={data} /> : <p role="status" className="text-sm text-muted">{loaded.error ?? 'Loading transaction…'}</p>}
  </div>
}
