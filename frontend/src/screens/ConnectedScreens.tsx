import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useApp } from '../store'
import { display, object, request, rows, type CaseData, type CaseSummary, type Json, type Row } from '../lib/backend'
import { Badge } from '../components/Badge'
import { TablePagination } from '../components/TablePagination'
import { StatusMessage } from '../components/StatusMessage'
import { navigationButton } from '../components/buttonStyles'
import { CorrelationGraph } from '../components/CorrelationGraph'
import { buildFlaggedGroups } from '../lib/correlation'
import { useAnalysisDetail } from '../lib/useAnalysisDetail'
import { useTablePage } from '../lib/useTablePage'
import { useScreenQuery, useNextPage, type ScreenPage } from '../lib/useScreenQuery'
import { LoadingPanel, QueryError } from '../components/LoadingPanel'
import { CoverageDetails } from '../components/CoverageDetails'
import { useRevealRow } from '../lib/useRevealRow'
import { RESULT_TONE, type CorrelationEdge, type ReconResult, type ReconRow, type RecordRef, type Transaction, type TxStatus, type EventType } from '../data/types'

const panel = 'rounded-md border border-line bg-panel p-4'
const input = 'rounded border border-line bg-page px-3 py-2 text-sm'
const select = 'h-[30px] rounded border border-line-input bg-panel px-2 text-xs text-ink'
function Button({ children, onClick, disabled = false, type = 'button' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit'
}) {
  const busy = useApp(s => s.busy)
  return <button type={type} disabled={disabled || busy} onClick={onClick}
    className={navigationButton}>{children}</button>
}
function Empty({ children }: { children: ReactNode }) {
  return <StatusMessage>{children}</StatusMessage>
}
function Detail({ value, title = 'Evidence details' }: { value: Json; title?: string }) {
  return <details className={panel}><summary className="cursor-pointer text-xs font-medium">{title}</summary>
    <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify(value, null, 2)}</pre></details>
}
function ProvenanceLinks({ value }: { value: Json | undefined }) {
  const references = Array.isArray(value) ? rows(value) : rows(object(value).log).concat(object(object(value).physical))
  const ids = [...new Set(references.map(ref => ref.tool_run_id).filter((id): id is string => typeof id === 'string' && !!id))]
  return <div className="flex flex-wrap gap-2">{ids.map(id => <Button key={id} onClick={() => {
    useApp.getState().selectTool(id); useApp.getState().go('prov')
  }}>Inspect source tool run · {id.slice(0, 8)}</Button>)}</div>
}
function Table({ data, columns, paginationKey, onSelect, selected, actionLabel = 'View', renderExpanded, rowKey = 'record_id', expandedRowId, onToggleExpanded, rowActions, serverPage }: {
  data: Row[]; columns: [string, string][]; paginationKey: string; onSelect?: (row: Row) => void; selected?: (row: Row) => boolean; actionLabel?: string; renderExpanded?: (row: Row) => ReactNode; rowKey?: string; expandedRowId?: string; onToggleExpanded?: (row: Row) => void
  rowActions?: (row: Row) => ReactNode
  serverPage?: { page: number; total: number; change: (page: number) => void }
}) {
  const [page, setPage] = useTablePage(paginationKey, paginationKey !== 'cases')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const size = 100
  const pages = Math.max(1, Math.ceil((serverPage?.total ?? data.length) / size))
  const current = Math.min(serverPage?.page ?? page, pages - 1)
  const activeId = expandedRowId ?? expandedId
  const tableRef = useRevealRow(`${activeId ?? ''}:${current}`)
  const expandedIndex = expandedRowId ? data.findIndex(row => String(row[rowKey]) === expandedRowId) : -1
  useEffect(() => {
    if (!serverPage && expandedIndex >= 0) setPage(Math.floor(expandedIndex / size))
  }, [expandedRowId, expandedIndex, setPage, serverPage])
  if (!data.length) return <Empty>No results available yet.</Empty>
  return <div ref={tableRef} className="overflow-auto rounded-md border border-line bg-panel">
    <table className="w-full text-left text-xs"><thead className="bg-thead text-dim"><tr>
      {columns.map(([key, label]) => <th key={key} className="px-3 py-2 font-semibold">{label}</th>)}
      {(onSelect || renderExpanded) && <th className="px-3 py-2">{rowActions ? 'Actions' : renderExpanded && rowKey === 'record_id' ? 'Comparisons' : 'Details'}</th>}
    </tr></thead><tbody>{(serverPage ? data : data.slice(current * size, (current + 1) * size)).map((row, index) =>
      <Fragment key={renderExpanded ? String(row[rowKey]) : current * size + index}><tr data-selected={selected?.(row) || !!(renderExpanded && activeId === String(row[rowKey]))} className={'border-t border-line ' + (selected?.(row) || (renderExpanded && activeId === String(row[rowKey])) ? 'bg-accent-soft' : '')}>
        {columns.map(([key]) => <td key={key} className={'max-w-xs break-words px-3 py-2 ' + (paginationKey === 'reconciliation' && key === 'result' ? '' : 'font-mono')}>
          {paginationKey === 'reconciliation' && key === 'result'
            ? <Badge tone={RESULT_TONE[String(row[key]) as ReconResult] ?? 'neutral'}>{display(row[key])}</Badge>
            : display(row[key])}
        </td>)}
        {onSelect && <td className="px-3 py-2"><div className="flex items-center gap-3"><button type="button" className={navigationButton} onClick={() => onSelect(row)}>{actionLabel}</button>{rowActions?.(row)}</div></td>}
        {renderExpanded && <td className="px-3 py-2"><button type="button" aria-expanded={activeId === String(row[rowKey])} className="inline-flex items-center gap-1 whitespace-nowrap text-accent" onClick={() => onToggleExpanded ? onToggleExpanded(row) : setExpandedId(activeId === String(row[rowKey]) ? null : String(row[rowKey]))}>
          <span className="underline">{rowKey === 'record_id' ? `${activeId === String(row[rowKey]) ? 'Hide' : 'View'} comparisons` : activeId === String(row[rowKey]) ? 'Hide run' : actionLabel}</span><span aria-hidden="true" className="text-[16px] leading-none">{activeId === String(row[rowKey]) ? '▴' : '▾'}</span>
        </button></td>}
      </tr>{renderExpanded && activeId === String(row[rowKey]) && <tr className="border-t border-line bg-thead"><td colSpan={columns.length + 1} className="p-3">{renderExpanded(row)}</td></tr>}</Fragment>)}</tbody></table>
    <TablePagination page={current} count={serverPage?.total ?? data.length} onPage={serverPage?.change ?? setPage} />
  </div>
}

export function CasesScreen() {
  const cases = useApp(s => s.cases)
  const busy = useApp(s => s.busy)
  const [deleting, setDeleting] = useState<CaseSummary | null>(null)
  const [name, setName] = useState('')
  const examiner = useApp(s => s.user?.username ?? '')
  const [filter, setFilter] = useState('')
  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (await useApp.getState().createCase(name)) setName('')
  }
  return <div className="space-y-4">
    <form className={panel + ' flex flex-wrap items-end gap-3'} onSubmit={create}>
      <label className="flex flex-col gap-1 text-xs">Case name<input className="h-[30px] rounded border border-line bg-page px-3 text-xs text-ink" required value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="flex flex-col gap-1 text-xs">Examiner<input className="h-[30px] rounded border border-line bg-page px-3 text-xs text-ink" readOnly value={examiner} /></label>
      <Button type="submit" disabled={!name.trim() || !examiner.trim()}>Create case</Button>
      <Button onClick={() => { void useApp.getState().refresh() }}>Refresh cases</Button>
    </form>
    <input aria-label="Filter cases" className={input} placeholder="Filter cases…" value={filter} onChange={e => setFilter(e.target.value)} />
    <Table paginationKey="cases" data={cases.filter(c => (c.name + c.examiner + c.id).toLowerCase().includes(filter.toLowerCase())).map(c => ({ ...c }))}
      columns={[['name', 'Case'], ['examiner', 'Examiner'], ['opened', 'Created'], ['files', 'Files'], ['status', 'Status']]}
      onSelect={row => { void useApp.getState().openCase(String(row.id)) }}
      rowActions={row => <button type="button" disabled={busy} aria-label={`Delete case ${String(row.name)}`} className="inline-flex items-center justify-center gap-1.5 rounded border border-line bg-[#fbe7e7] px-3 py-1.5 font-sans text-xs font-medium text-danger hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-40" onClick={() => {
        useApp.setState({ error: null })
        setDeleting(cases.find(item => item.id === row.id) ?? null)
      }}>Delete</button>} />
    {deleting && <DeleteCaseDialog caseInfo={deleting} onClose={() => setDeleting(null)} />}
  </div>
}

function DeleteCaseDialog({ caseInfo, onClose }: { caseInfo: CaseSummary; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [confirmation, setConfirmation] = useState('')
  const busy = useApp(s => s.busy)
  const error = useApp(s => s.error)
  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => element?.close()
  }, [])
  return <dialog ref={dialog} aria-labelledby="delete-case-heading" aria-describedby="delete-case-description" onCancel={event => {
    if (busy) event.preventDefault()
    else onClose()
  }} className="w-full max-w-md rounded-lg border border-line bg-panel p-6 text-ink shadow-xl backdrop:bg-black/40">
    <form className="space-y-4" onSubmit={event => {
      event.preventDefault()
      if (confirmation === caseInfo.name) void useApp.getState().deleteCase(caseInfo.id, confirmation).then(deleted => { if (deleted) onClose() })
    }}>
      <h2 id="delete-case-heading" className="text-lg font-semibold">Delete case permanently?</h2>
      <p id="delete-case-description" className="text-sm">Deleting <strong>{caseInfo.name}</strong> removes its database, working copies, outputs, logs and reports stored in its folder. Original evidence files and exports outside that folder remain untouched. This cannot be undone.</p>
      <label className="block text-sm">Type the case name to confirm<input autoFocus required autoComplete="off" className={input + ' mt-2 w-full'} value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div className="flex justify-end gap-3"><Button onClick={onClose}>Cancel</Button><button type="submit" disabled={busy || confirmation !== caseInfo.name} className="rounded border border-danger bg-danger px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">{busy ? 'Deleting…' : 'Delete case'}</button></div>
    </form>
  </dialog>
}

export { IntakeScreen } from './IntakeScreen'

export { PipelineScreen } from './PipelineScreen'

export { TimelineScreen } from './TimelineScreen'

export { RecordHistoryScreen } from './RecordHistoryScreen'

function graphData(data: ReturnType<typeof useApp.getState>['data']) {
  const recordRefs: RecordRef[] = rows(data?.analysis.correlation?.records).map(c => {
    const r = object(c.record)
    return { id: String(r.id), table: display(r.table), key: display(r.key), pk: display(r.pk), label: display(r.label) }
  })
  const status: Record<string, TxStatus> = { committed: 'Committed', rolled_back: 'Rolled back', incomplete: 'Incomplete' }
  const transactions: Transaction[] = rows(data?.analysis.grouping?.transactions).map((t, order) => ({
    order,
    id: String(t.id), status: status[String(t.status)] ?? 'Incomplete', summary: (t.event_count ?? rows(t.events).length) + ' events',
    when: display(t.commit_timestamp), binlogFile: String(t.source_file), binlogPos: Number(t.start_position),
  }))
  const edges: CorrelationEdge[] = rows(data?.analysis.correlation?.edges).map(e => ({ txId: String(e.tx_id), recordId: String(e.record_id), eventType: String(e.event_type) as EventType }))
  const recon: ReconRow[] = rows(data?.analysis.reconciliation?.rows).map(r => ({ recordId: String(r.record_id), field: String(r.field), log: String(r.log_display), phys: String(r.phys_display), result: String(r.result) as ReconResult }))
  return buildFlaggedGroups(recordRefs, transactions, edges, recon)
}
function ProgressiveGraphs({ data }: { data: CaseData }) {
  const [loaded, setLoaded] = useState<CaseData>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const loadedKey = useRef('')
  const active = useApp(s => s.screen === 'recon' && !s.locked)
  const revision = useApp(s => s.preview?.revision)
  const expanded = useApp(s => s.expandedGroups)
  useEffect(() => {
    if (!active) return
    const key = `${data.case.case_id}:${revision}:${attempt}`
    if (loaded && loadedKey.current === key) return
    let alive = true
    const load = async () => {
      const collections: Record<string, Row[]> = {}
      for (const kind of ['graph_records', 'graph_edges', 'transactions', 'comparisons']) {
        const values: Row[] = []
        let offset = 0, total = Infinity
        while (alive && offset < total) {
          const page = await request<ScreenPage>('get_screen_page', { case_id: data.case.case_id, kind, offset, limit: 100 }, { valid: () => alive, background: true })
          if (!alive) return
          values.push(...page.items); total = page.total; offset += 100
        }
        if (!alive) return
        collections[kind] = values
      }
      if (alive) { loadedKey.current=key; setLoaded({ ...data, analysis: { correlation: { records: collections.graph_records, edges: collections.graph_edges },
        grouping: { transactions: collections.transactions }, reconciliation: { rows: collections.comparisons } } }) }
    }
    setError('')
    void load().catch(e => { if (alive) setError(String(e)) })
    return () => { alive = false }
  }, [active, data, revision, attempt, loaded])
  const groups = useMemo(() => graphData(loaded ?? null), [loaded])
  if (!loaded) return <LoadingPanel error={error} retry={() => setAttempt(n => n + 1)} label="Loading correlation graphs" />
  return <>{groups.map(group => <div key={group.id} className="space-y-2"><Button onClick={() => useApp.getState().toggleGroup(group.id)}>{expanded.includes(group.id) ? 'Hide' : 'Show'} correlation graph · {group.records.length} records</Button>{expanded.includes(group.id) && <CorrelationGraph group={group} />}</div>)}{!groups.length && <StatusMessage>No flagged correlation groups.</StatusMessage>}</>
}

function RecordComparisons({ recordId, comparisons, data }: { recordId: string; comparisons: Row[]; data: CaseData }) {
  const [detail, setDetail] = useState<Row | null>(null)
  const [page, setPage] = useTablePage(`comparisons:${recordId}`)
  const legacy = Array.isArray(data.analysis.reconciliation?.rows)
  const payload = { kind: 'comparisons', identity: recordId, offset: page * 100, limit: 100 }
  const query = useScreenQuery<ScreenPage>('get_screen_page', payload, 'recon', !legacy)
  useNextPage(query.value, payload, 'recon')
  const fields = legacy ? comparisons : query.value?.items ?? []
  const loaded = useAnalysisDetail(data.case.case_id, 'comparison', detail ?? undefined, !legacy || data.analysis.reconciliation?.details_deferred === true, detail ? String(detail.field) : undefined)
  return <div className="space-y-3">
    <QueryError error={query.error || loaded.error} retry={query.error ? query.retry : loaded.retry} />
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs font-medium text-ink">Individual comparisons · {recordId}</span>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => useApp.getState().openRecord(recordId)}>Open record history</Button>
        {loaded.detail && <ProvenanceLinks value={loaded.detail.provenance} />}
      </div>
    </div>
    <div className="overflow-auto rounded border border-line bg-panel"><table className="w-full text-left text-xs">
      <thead className="bg-thead text-dim"><tr>{['Field', 'Log-derived', 'Physical', 'Result', 'Rule', 'Details'].map(label => <th key={label} className="px-3 py-2 font-semibold">{label}</th>)}</tr></thead>
      <tbody>{fields.map(field => <tr key={String(field.field)} className={'border-t border-line ' + (detail?.field === field.field ? 'bg-accent-soft' : '')}>
        <td className="px-3 py-2 font-mono">{display(field.field)}</td><td className="max-w-xs break-words px-3 py-2 font-mono">{display(field.log_display)}</td><td className="max-w-xs break-words px-3 py-2 font-mono">{display(field.phys_display)}</td>
        <td className="px-3 py-2"><Badge tone={RESULT_TONE[String(field.result) as ReconResult] ?? 'neutral'}>{display(field.result)}</Badge></td><td className="px-3 py-2 font-mono">{display(field.rule_id)}</td>
        <td className="px-3 py-2"><button type="button" className="text-accent underline" onClick={() => setDetail(field)}>View</button></td>
      </tr>)}</tbody>
    </table></div>
    {!legacy && !query.value ? <LoadingPanel error={query.error} retry={query.retry} label="Loading comparisons" /> : !fields.length && <StatusMessage>No individual comparisons available.</StatusMessage>}
    {!legacy && query.value && <TablePagination page={page} count={query.value.total} onPage={setPage} />}
    {detail && (loaded.detail ? <section aria-label="Comparison values, rule and source provenance" className="overflow-hidden rounded border border-line bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-line bg-thead px-3 py-2">
        <h3 className="text-xs font-semibold text-ink">Comparison values, rule and source provenance</h3>
        <button type="button" className="text-xs font-medium text-accent hover:underline" onClick={() => setDetail(null)}>Close</button>
      </div>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all p-3 font-mono text-xs">{JSON.stringify(loaded.detail, null, 2)}</pre>
    </section> : <StatusMessage error={!!loaded.error}>{loaded.error ?? 'Loading comparison…'}</StatusMessage>)}
  </div>
}

export function ReconciliationScreen() {
  const data = useApp(s => s.data)
  const selectedRecord = useApp(s => s.selectedRecord)
  const [filter, setFilter] = useState('')
  const [page, setPage] = useTablePage(`reconciliation:${filter}`)
  const legacy = Array.isArray(data?.analysis.reconciliation?.records)
  const payload = { kind: 'reconciliation', offset: page * 100, limit: 100, ...(filter ? { bucket: filter } : {}) }
  const query = useScreenQuery<ScreenPage>('get_screen_page', payload, 'recon', !legacy)
  useNextPage(query.value, payload, 'recon')
  const location = useScreenQuery<{ offset: number }>('locate_screen_item', { kind: 'reconciliation', identity: selectedRecord }, 'recon', !legacy && !filter && !!selectedRecord && !!query.value && !query.value.items.some(r => r.record_id === selectedRecord))
  useEffect(() => { if (location.value) setPage(location.value.offset / 100) }, [location.value, setPage])
  const [showGraphs, setShowGraphs] = useState(false)
  const [summary,setSummary] = useState<{caseId:string;counts:Row}>()
  const savedCounts=query.value?.summaries?.reconciliation?.counts
  const caseId=data?.case.case_id
  useEffect(()=>{if(savedCounts && caseId) setSummary({caseId,counts:object(savedCounts)})},[savedCounts,caseId])
  const navigation = useApp(s => s.reconciliationNavigation)
  useEffect(() => { if(navigation) setFilter('') }, [navigation])
  const expanded = useApp(s => s.expandedGroups)
  const groups = useMemo(() => graphData(data), [data])
  const comparisonsByRecord = useMemo(() => {
    const grouped = new Map<string, Row[]>()
    for (const field of rows(data?.analysis.reconciliation?.rows)) {
      const id = String(field.record_id)
      const fields = grouped.get(id) ?? []
      fields.push(field)
      grouped.set(id, fields)
    }
    return grouped
  }, [data?.analysis.reconciliation?.rows])
  const all = useMemo(() => rows(data?.analysis.reconciliation?.records).map(record => ({
    record_id: String(object(record.record).id), result: record.rollup,
    summary: record.rollup_label, rule_id: record.rollup_rule_id,
    field_count: record.field_count ?? rows(record.fields).length,
  })), [data?.analysis.reconciliation?.records])
  const resultCounts=savedCounts ? object(savedCounts) : summary?.caseId===data?.case.case_id ? summary?.counts : undefined
  const counts = Object.keys(RESULT_TONE).map(result => [result, legacy ? all.filter(r => r.result === result).length : resultCounts ? Number(resultCounts[result] ?? 0) : null] as const)
  if (!data) return <StatusMessage>Open a case to view reconciliation.</StatusMessage>
  return <div className="space-y-4">
    <QueryError error={query.error || location.error} retry={query.error ? query.retry : location.retry} />
    <div className="grid grid-cols-6 gap-2">{counts.map(([result, count]) => <div key={result} className={panel}><p className="font-mono text-xl font-semibold">{count ?? '—'}</p><Badge tone={RESULT_TONE[result as ReconResult]}>{result}</Badge></div>)}</div>
    <label className="flex items-center gap-2 text-xs text-muted">Filter result<select className={select} value={filter} onChange={e => {setFilter(e.target.value);useApp.getState().selectRecord('')}}><option value="">All results</option>{counts.map(([r]) => <option key={r}>{r}</option>)}</select></label>
    <p className="text-xs text-muted">Results count records. Expand a row to inspect its individual field comparisons.</p>
    {!legacy && !query.value ? <LoadingPanel error={query.error} retry={query.retry} label="Loading reconciliation" /> : <Table paginationKey="reconciliation" data={legacy ? all.filter(r => !filter || r.result === filter) : query.value?.items ?? []} columns={[['record_id', 'Record'], ['result', 'Result'], ['summary', 'Summary'], ['field_count', 'Comparisons'], ['rule_id', 'Rule']]}
      serverPage={legacy ? undefined : { page, total: query.value?.total ?? 0, change: value => { useApp.getState().selectRecord(''); setPage(value) } }}
      expandedRowId={selectedRecord} onToggleExpanded={record => useApp.getState().selectRecord(selectedRecord === String(record.record_id) ? '' : String(record.record_id))}
      renderExpanded={record => data && <RecordComparisons key={String(record.record_id)} recordId={String(record.record_id)} comparisons={comparisonsByRecord.get(String(record.record_id)) ?? []} data={data} />} />}
    {groups.map(group => <div key={group.id} className="space-y-2"><Button onClick={() => useApp.getState().toggleGroup(group.id)}>{expanded.includes(group.id) ? 'Hide' : 'Show'} correlation graph · {group.records.length} records</Button>{expanded.includes(group.id) && <CorrelationGraph group={group} />}</div>)}
    {data?.analysis.reconciliation?.coverage && <Detail value={data.analysis.reconciliation.coverage} title="Coverage and limits" />}
    {!legacy && data && <><Button onClick={() => setShowGraphs(!showGraphs)}>{showGraphs ? 'Hide' : 'Show'} correlation graphs</Button>{showGraphs && <ProgressiveGraphs data={data} />}</>}
    {!legacy && <CoverageDetails kind="reconciliation" screen="recon" title="Coverage and limits" />}
  </div>
}

export { GapsScreen } from './GapsScreen'

function ToolRunDetails({ run, caseId }: { run: Row; caseId: string }) {
  const [stream, setStream] = useState('stdout')
  const [preview, setPreview] = useState<{ text: string; truncated: boolean; sha256?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => { setPreview(null) }, [stream])
  const read = async () => {
    setLoading(true)
    try { setPreview(await request('read_tool_output', { case_id: caseId, run_id: run.tool_run_id, stream })) }
    catch (error) { useApp.getState().setError(error) }
    finally { setLoading(false) }
  }
  return <div className="space-y-4">
    <section className="overflow-hidden rounded border border-line bg-panel" aria-label="Command, executable hash and raw output hashes">
      <div className="border-b border-line bg-thead px-3 py-2">
        <h3 className="text-xs font-semibold text-ink">{display(run.tool_name)} · Command, executable hash and raw output hashes</h3>
      </div>
      <div className="p-3">
        <p className="mb-3 text-xs text-muted">Run by: {run.actor_username == null ? 'Not recorded (older run)' : display(run.actor_username)}{run.actor_id != null ? ` · Actor ID: ${display(run.actor_id)}` : ''}</p>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify(run, null, 2)}</pre>
      </div>
    </section>
      <div className="flex items-center gap-3"><select aria-label="Output stream" className={select} value={stream} onChange={e => setStream(e.target.value)}><option>stdout</option><option>stderr</option></select>
        <Button disabled={loading} onClick={() => { void read() }}>{loading ? 'Loading…' : 'Read raw output'}</Button></div>
      {preview && <div className={panel}><p className="mb-2 break-all font-mono text-xs">SHA-256: {preview.sha256 ?? 'No output recorded'}{preview.truncated ? ' · Preview limited to 256 KiB' : ''}</p>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{preview.text || '(empty output)'}</pre></div>}
  </div>
}

export function ProvenanceScreen() {
  const data = useApp(s => s.data)
  const selected = useApp(s => s.selectedTool)
  const [page,setPage] = useTablePage('tool-run-pages')
  const legacy = Array.isArray(data?.tables.tool_runs)
  const payload = {kind:'tool_runs',offset:page*100,limit:100}
  const query = useScreenQuery<ScreenPage>('get_screen_page',payload,'prov',!legacy)
  useNextPage(query.value,payload,'prov')
  const location = useScreenQuery<{offset:number}>('locate_screen_item',{kind:'tool_runs',identity:selected},'prov',!legacy && !!selected && !!query.value && !query.value.items.some(run=>run.tool_run_id===selected))
  useEffect(()=>{if(location.value) setPage(location.value.offset/100)},[location.value,setPage])
  if (!data) return <StatusMessage>Open a case to view provenance.</StatusMessage>
  if (!legacy && !query.value) return <LoadingPanel error={query.error} retry={query.retry} label="Loading source tool runs" />
  return <Table paginationKey="tool-runs" data={legacy ? data?.tables.tool_runs ?? [] : query.value?.items ?? []}
    serverPage={legacy ? undefined : {page,total:query.value?.total ?? 0,change:value=>{useApp.getState().selectTool('');setPage(value)}}}
    columns={[['tool_name', 'Utility'], ['tool_version', 'Version'], ['status', 'Status'], ['exit_code', 'Exit'], ['evidence_id', 'Evidence'], ['started_at', 'Started']]}
    rowKey="tool_run_id" actionLabel="Inspect run" expandedRowId={selected}
    onToggleExpanded={run => useApp.getState().selectTool(selected === String(run.tool_run_id) ? '' : String(run.tool_run_id))}
    selected={run => run.tool_run_id === selected}
    renderExpanded={run => data && <ToolRunDetails key={String(run.tool_run_id)} run={run} caseId={data.case.case_id} />} />
}

export { ReportScreen } from './ReportScreen'

export { SettingsScreen } from './SettingsScreen'
