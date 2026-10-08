import { useMemo, useState } from 'react'
import { Badge } from '../components/Badge'
import { RESULT_TONE, type ReconResult } from '../data/types'
import { display, object, rows, type CaseData, type Json, type Row } from '../lib/backend'
import { useApp } from '../store'
import { useAnalysisDetail } from '../lib/useAnalysisDetail'

const button = 'h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-page disabled:cursor-not-allowed disabled:opacity-40'
const methods: Record<string, string> = {
  primary_key_exact: 'Primary-key exact match', composite_primary_key_exact: 'Composite primary-key exact match',
  primary_key_update_continuity: 'Linked across a primary-key change', log_only_no_physical_counterpart: 'Log evidence only; no physical counterpart',
  physical_only_no_log_events: 'Physical evidence only; no log events', ambiguous: 'Identity match is ambiguous',
  table_has_no_primary_key: 'Table has no primary key', schema_not_available: 'Schema unavailable', key_columns_not_in_row_image: 'Key columns missing from row image',
}
const kinds: Record<string, { title: string; note: string; color: string }> = {
  earliest_observed_state: { title: 'Earliest observed state', note: 'The first available log event establishes this starting point. Earlier history is unknown.', color: 'bg-dim' },
  event: { title: 'Committed event', note: 'This event contributes to the committed log state.', color: 'bg-accent' },
  rolled_back_event: { title: 'Rolled-back event', note: 'The event is recorded in the log but does not change the committed log state.', color: 'bg-dim' },
  uncommitted_event: { title: 'Uncommitted event', note: 'No commit was observed. This event does not change the committed log state.', color: 'bg-amber' },
  identity_change: { title: 'Record identity changed', note: 'The engine linked this record across a primary-key change.', color: 'bg-accent' },
  coverage_gap: { title: 'Gap in log coverage', note: 'Missing or incomplete evidence limits what this history can establish.', color: 'bg-amber' },
  physical_state: { title: 'Physical state in .ibd', note: 'An independent row observation extracted from the tablespace; it is not a replayed log event.', color: 'bg-ok' },
}

function reference(value: Json | undefined): string {
  return Array.isArray(value) ? `${display(value[0])} · pos ${display(value[1])} · row ${display(value[2])}` : 'Source position not recorded'
}
function eventKey(value: Json | undefined): string {
  return Array.isArray(value) ? JSON.stringify(value) : ''
}
function ValueChips({ values }: { values: Row }) {
  return <dl className="mt-2 flex flex-wrap gap-2">{Object.entries(values).map(([field, value]) =>
    <div key={field} className="flex max-w-full flex-wrap gap-1.5 rounded-[3px] border border-line-mid bg-page px-2 py-[3px] font-mono text-[11px]">
      <dt className="text-dim">{field}</dt><dd className="break-all">{display(value)}</dd>
    </div>)}{!Object.keys(values).length && <p className="text-[11px] text-muted">No field values observed.</p>}</dl>
}

function Changes({ changes, showMeaning = true }: { changes: Row[]; showMeaning?: boolean }) {
  return <div className="mt-2 overflow-auto rounded border border-line-mid">
    <table className="w-full min-w-[480px] table-fixed text-left">
      <thead className="bg-thead text-[10px] uppercase tracking-[.07em] text-dim"><tr>
        {(showMeaning ? ['Column', 'Before', 'After', 'Change'] : ['Column', 'Before', 'After']).map(label => <th key={label} className="px-2 py-[5px] font-semibold">{label}</th>)}
      </tr></thead>
      <tbody>{changes.map(change => <tr key={String(change.column)} className="border-t border-line-mid font-mono text-[11px]">
        <td className="break-words px-2 py-[5px]">{display(change.column)}</td>
        <td className="break-words px-2 py-[5px] text-muted">{display(change.before)}</td>
        <td className={'break-words px-2 py-[5px] ' + (change.changed === true ? 'bg-accent-soft font-medium text-accent' : 'text-muted')}>{display(change.after)}</td>
        {showMeaning && <td className="px-2 py-[5px] text-muted">{change.changed === true ? 'Changed' : change.changed === false ? 'Unchanged' : 'Unknown'}</td>}
      </tr>)}</tbody>
    </table>
  </div>
}

function Findings({ findings, data }: { findings: Row[]; data: CaseData }) {
  if (!findings.length) return null
  return <details className="mt-2 text-[11px] text-muted">
    <summary className="cursor-pointer">Findings and reasoning ({findings.length})</summary>
    {findings.map((finding, index) => {
      const described = data.findings.find(f => f.rule_id === finding.rule_id && JSON.stringify(f.subject) === JSON.stringify(finding.subject) && JSON.stringify(f.context) === JSON.stringify(finding.context))
      return <div key={index} className="mt-2 rounded border border-line p-2">
        <p><span className="font-mono">{display(finding.rule_id)}</span> · {display(finding.severity)}</p>
        {described?.description && <p className="mt-1">{display(described.description)}</p>}
        <dl className="mt-1">{Object.entries(object(finding.context)).map(([key, value]) => <div key={key} className="flex flex-wrap gap-1"><dt>{key.replaceAll('_', ' ')}:</dt><dd className="break-all font-mono">{display(value)}</dd></div>)}</dl>
      </div>
    })}
  </details>
}

function Step({ step, history, event, data, last, firstInsert = false }: { step: Row; history: Row; event?: Row; data: CaseData; last: boolean; firstInsert?: boolean }) {
  const kind = kinds[String(step.kind)] ?? { title: display(step.kind), note: '', color: 'bg-dim' }
  const changes = rows(step.changes)
  const provenance = object(step.provenance)
  const physical = step.kind === 'physical_state'
  const earliest = step.kind === 'earliest_observed_state'
  const eventFields = [...new Set([...Object.keys(object(event?.before)), ...Object.keys(object(event?.after))])]
  return <li className="grid grid-cols-[16px_minmax(0,1fr)] gap-3 pb-0.5 pt-3">
    <div className="flex flex-col items-center pt-1">
      <span aria-hidden="true" className={'h-[9px] w-[9px] flex-none rounded-full ' + kind.color} />
      {!last && <span aria-hidden="true" className="mt-1 min-h-[34px] w-px flex-1 bg-line" />}
    </div>
    <div className="min-w-0 pb-3">
      <div className="flex flex-wrap items-center gap-[9px]">
        <h3 className="text-[12.5px] font-semibold">{step.transaction_id ? `${display(step.transaction_id)} · ${event?.event_type ? display(event.event_type) : kind.title}` : kind.title}</h3>
        {firstInsert && <Badge tone="info">Earliest observed event</Badge>}
        {step.transaction_status && <Badge tone={step.transaction_status === 'committed' ? 'ok' : step.transaction_status === 'rolled_back' ? 'neutral' : 'warn'}>{display(step.transaction_status).replaceAll('_', ' ')}</Badge>}
        <span className="font-mono text-[11px] text-dimmer">{physical ? `${display(provenance.source_file)} · ${display(provenance.tool_name)}` : reference(step.ref)}</span>
      </div>
      <p className="mt-0.5 text-[11.5px] text-muted">{kind.note}</p>
      {firstInsert && <p className="mt-0.5 text-[11.5px] text-muted">This INSERT is the row’s first observed appearance in the imported logs. The row was absent immediately before it; earlier history is unknown.</p>}
      <p className="mt-1 text-[11px] text-muted">Step {display(step.index)} · rule <span className="font-mono">{display(step.rule_id)}</span>
        {step.timestamp ? ` · ${display(step.timestamp)}` : ''}
        {physical ? ` · Row ${display(step.presence_after)}` : step.kind === 'event' || step.kind === 'rolled_back_event' || step.kind === 'uncommitted_event' ? ` · Committed row presence: ${display(step.presence_before)} → ${display(step.presence_after)}` : ''}
      </p>
      {earliest && <><p className="mt-2 text-[11px] text-muted">Row {display(object(history.earliest_state).presence)}</p>{object(history.earliest_state).presence !== 'absent' && <ValueChips values={object(object(history.earliest_state).values)} />}</>}
      {physical ? <ValueChips values={Object.fromEntries(changes.map(change => [String(change.column), change.after ?? null]))} /> : changes.length > 0 && <>
        <p className="mt-2 text-[11px] font-medium text-muted">Effect on committed state</p><Changes changes={changes} />
      </>}
      {event && <details className="mt-2 text-[11px] text-muted"><summary className="cursor-pointer">Observed log row images{step.durable === false ? ' (not applied to committed state)' : ''}</summary>
        <p className="mt-1">These are the recorded event values. Unobserved fields remain unknown.</p>
        <Changes showMeaning={false} changes={eventFields.map(column => ({ column, before: event.before == null ? '[no row image]' : column in object(event.before) ? object(event.before)[column] : { __unobserved__: true }, after: event.after == null ? '[no row image]' : column in object(event.after) ? object(event.after)[column] : { __unobserved__: true }, changed: null }))} />
      </details>}
      <div className="mt-2 flex flex-wrap gap-2">
        {step.transaction_id && <button type="button" className={button} onClick={() => useApp.getState().openTransaction(String(step.transaction_id))}>Open transaction</button>}
        {typeof provenance.tool_run_id === 'string' && <button type="button" className={button} onClick={() => {
          useApp.getState().selectTool(String(provenance.tool_run_id)); useApp.getState().go('prov')
        }}>Inspect source tool run</button>}
      </div>
      <Findings findings={rows(step.findings)} data={data} />
    </div>
  </li>
}

function HistoryDetail({ history, data }: { history: Row; data: CaseData }) {
  const [page, setPage] = useState(0)
  const record = object(history.record)
  const steps = rows(history.steps)
  const eventMap = useMemo(() => {
    const map = new Map<string, Row>()
    for (const event of rows(history.events)) map.set(JSON.stringify([event.source_file, event.log_position, event.row_index]), event)
    for (const transaction of rows(data.analysis.grouping?.transactions)) for (const grouped of rows(transaction.events)) {
      const event = object(grouped.event)
      map.set(JSON.stringify([event.source_file, event.log_position, event.row_index]), event)
    }
    for (const grouped of rows(data.analysis.grouping?.ungrouped_events)) {
      const event = object(grouped.event)
      map.set(JSON.stringify([event.source_file, event.log_position, event.row_index]), event)
    }
    return map
  }, [data.analysis.grouping, history.events])
  const seed = steps.find(step => step.kind === 'earliest_observed_state')
  const firstEvent = steps.find(step => ['event', 'rolled_back_event', 'uncommitted_event'].includes(String(step.kind)))
  const startsWithInsert = !!(seed && firstEvent && object(history.earliest_state).presence === 'absent' &&
    eventKey(seed.ref) === eventKey(firstEvent.ref) && eventMap.get(eventKey(firstEvent.ref))?.event_type === 'INSERT')
  const timelineSteps = startsWithInsert ? steps.filter(step => step !== seed) : steps
  const pages = Math.max(1, Math.ceil(timelineSteps.length / 100))
  const current = Math.min(page, pages - 1)
  const states = [object(history.earliest_state), object(history.final_log_state), object(history.speculative_state)]
  const fields = [...new Set(states.flatMap(state => Object.keys(object(state.values))))]
  const gaps = rows(history.coverage_gaps_touching)
  const partial = Array.isArray(history.partial_image_columns) ? history.partial_image_columns : []
  const comparisons = rows(data.analysis.reconciliation?.rows).filter(row => row.record_id === record.id)
  return <div className="min-w-0 space-y-3">
    <section className="rounded-md border border-line bg-panel px-3.5 py-[13px]">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 className="break-all font-mono text-[15px] font-semibold">{display(record.table)} · {display(record.key)}</h2>
        <p className="text-[11.5px] text-muted">{methods[String(history.method)] ?? display(history.method).replaceAll('_', ' ')}</p>
      </div>
      {(gaps.length > 0 || partial.length > 0 || history.before_image_mismatch === true) && <div className="mt-3 rounded border border-line bg-page p-2 text-[11px] text-muted">
        <p className="font-semibold">Limits to this reconstruction</p>
        {gaps.length > 0 && <p>{gaps.length} coverage gaps affect this record. The logs cannot establish a complete history.</p>}
        {partial.length > 0 && <p>Incomplete row images: {partial.map(display).join(', ')}.</p>}
        {history.before_image_mismatch === true && <p>A recorded before-image disagrees with the replayed state. Review the findings before drawing conclusions.</p>}
        {gaps.map((gap, index) => <p key={index} className="mt-1">{display(gap.reason).replaceAll('_', ' ')} · after {display(gap.after_file)}{Array.isArray(gap.missing_files) && gap.missing_files.length > 0 ? ` · missing ${gap.missing_files.map(display).join(', ')}` : ''}</p>)}
      </div>}
    </section>
    <section aria-labelledby="history-timeline-heading" className="rounded-md border border-line bg-panel pb-3.5">
      <div className="flex flex-wrap items-center gap-3 border-b border-line-soft px-3.5 py-2.5">
        <h2 id="history-timeline-heading" className="text-[12px] font-semibold">Record history</h2>
        {[['bg-dim', 'Starting point / rolled back'], ['bg-accent', 'Committed / identity'], ['bg-amber', 'Uncommitted / gap'], ['bg-ok', 'Physical row']].map(([color, label]) => <span key={label} className="flex items-center gap-1.5 text-[11px] text-muted"><span aria-hidden="true" className={'h-[7px] w-[7px] rounded-full ' + color} />{label}</span>)}
      </div>
      {startsWithInsert && seed && <details className="mx-3.5 mt-3 text-[11px] text-muted">
        <summary className="cursor-pointer">Before first observed INSERT: row absent</summary>
        <p className="mt-1">No field values exist for an absent row. This starting point is inferred from the INSERT at {reference(seed.ref)}.</p>
        <Findings findings={rows(seed.findings)} data={data} />
      </details>}
      <ol className="px-3.5 pt-1">{timelineSteps.slice(current * 100, (current + 1) * 100).map((step, index) => <Step key={String(step.index)} step={step} history={history} data={data} event={eventMap.get(eventKey(step.ref))} firstInsert={startsWithInsert && step === firstEvent} last={index === Math.min(100, timelineSteps.length - current * 100) - 1} />)}</ol>
      {!timelineSteps.length && <p className="px-3.5 py-3 text-[11px] text-muted">No history steps available.</p>}
      {pages > 1 && <div className="flex items-center gap-3 px-3.5 pt-3 text-[11px] text-muted"><button type="button" className={button} disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button><span>Page {current + 1} of {pages} · {timelineSteps.length} timeline entries</span><button type="button" className={button} disabled={current + 1 === pages} onClick={() => setPage(current + 1)}>Next</button></div>}
    </section>
    <section className="overflow-hidden rounded-md border border-line bg-panel" aria-labelledby="history-states-heading">
      <h2 id="history-states-heading" className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">Compare reconstructed states</h2>
      <p className="px-3 py-2 text-[11px] text-muted">Committed log state applies committed events only. Speculative state also applies rolled-back and uncommitted events; it is not an established database state.</p>
      <div className="overflow-auto"><table className="w-full min-w-[560px] table-fixed text-left">
        <thead className="bg-thead text-[10px] uppercase tracking-[.07em] text-dim"><tr>{['Column', startsWithInsert ? 'Before first observed INSERT' : 'Earliest observed state', 'Committed log state', 'Speculative state'].map(label => <th key={label} className="px-3 py-[5px] font-semibold">{label}</th>)}</tr></thead>
        <tbody><tr className="border-t border-line font-mono text-[11px]"><th className="px-3 py-[5px] font-medium">Row presence</th>{states.map((state, index) => <td key={index} className="px-3 py-[5px] text-muted">{display(state.presence)}</td>)}</tr>
          {fields.map(field => <tr key={field} className="border-t border-line font-mono text-[11px]"><th className="break-words px-3 py-[5px] font-medium">{field}</th>{states.map((state, index) => <td key={index} className="break-words px-3 py-[5px] text-muted">{state.presence === 'absent' ? 'No row' : display(object(state.values)[field])}</td>)}</tr>)}
        </tbody>
      </table></div>
    </section>
    {comparisons.length > 0 && <section className="rounded-md border border-line bg-panel p-3">
      <h2 className="text-[12px] font-semibold">Comparison with the physical row</h2>
      <p className="mt-1 text-[11px] text-muted">The reconciliation result for each field, including row presence.</p>
      <div className="mt-2 flex flex-wrap gap-2">{comparisons.map(comparison => <div key={String(comparison.field)} className="flex items-center gap-2 rounded border border-line px-2 py-1 text-[11px]"><span className="font-mono">{display(comparison.field)}</span><Badge tone={RESULT_TONE[String(comparison.result) as ReconResult] ?? 'neutral'}>{display(comparison.result)}</Badge></div>)}</div>
      <button type="button" className={button + ' mt-2'} onClick={() => useApp.getState().go('recon')}>Open reconciliation</button>
    </section>}
    <Findings findings={rows(history.findings)} data={data} />
    <details className="rounded-md border border-line bg-panel p-3 text-[11px]"><summary className="cursor-pointer font-medium">Full history, observed values and provenance</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono">{JSON.stringify(history, null, 2)}</pre></details>
  </div>
}

export function RecordHistoryScreen() {
  const data = useApp(s => s.data)
  const selected = useApp(s => s.selectedRecord)
  const histories = useMemo(() => rows(data?.analysis.reconstruction?.histories), [data?.analysis.reconstruction?.histories])
  const index = Math.max(0, histories.findIndex(history => object(history.record).id === selected))
  const current = histories[index]
  const loaded = useAnalysisDetail(data?.case.case_id, 'history', current, data?.analysis.reconstruction?.details_deferred === true)
  const page = Math.floor(index / 100)
  const pages = Math.max(1, Math.ceil(histories.length / 100))
  if (!data || !current) return <div className="rounded-md border border-line bg-panel p-4 text-sm text-muted">No results available yet.</div>
  return <div className="grid max-w-[1180px] items-start gap-4 lg:grid-cols-[250px_minmax(0,1fr)]">
    <section className="min-w-0 overflow-hidden rounded-md border border-line bg-panel" aria-labelledby="correlated-records-heading">
      <h2 id="correlated-records-heading" className="border-b border-line px-3 py-[9px] text-[12px] font-semibold">Correlated records</h2>
      <div className="max-h-[640px] overflow-auto">{histories.slice(page * 100, (page + 1) * 100).map(history => {
        const record = object(history.record)
        const count = history.step_count ?? rows(history.steps).length
        return <button type="button" key={String(record.id)} aria-pressed={record.id === object(current.record).id} onClick={() => useApp.getState().selectRecord(String(record.id))}
          className={'block w-full border-b border-l-2 border-line-soft px-3 py-[9px] text-left hover:bg-thead ' + (record.id === object(current.record).id ? 'border-l-accent bg-accent-soft' : 'border-l-transparent bg-panel')}>
          <span className="block break-all font-mono text-[12px]">{display(record.table)}</span><span className="mt-0.5 block text-[11px] text-muted">{display(record.key)} · {display(count)} steps</span>
        </button>
      })}</div>
      {pages > 1 && <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-muted"><button type="button" className={button} disabled={page === 0} onClick={() => useApp.getState().selectRecord(String(object(histories[(page - 1) * 100].record).id))}>Previous</button><span>{page + 1} / {pages}</span><button type="button" className={button} disabled={page + 1 === pages} onClick={() => useApp.getState().selectRecord(String(object(histories[(page + 1) * 100].record).id))}>Next</button></div>}
    </section>
    {loaded.detail ? <HistoryDetail key={`${data.case.case_id}:${object(current.record).id}`} history={loaded.detail} data={{ ...data, findings: [...data.findings, ...loaded.findings] }} /> : <p role="status" className="text-sm text-muted">{loaded.error ?? 'Loading record history…'}</p>}
  </div>
}
