import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useApp } from '../store'
import { display, object, pickExportPath, request, rows, type Json, type Row, type ToolSettings } from '../lib/backend'
import { Badge } from '../components/Badge'
import { CorrelationGraph } from '../components/CorrelationGraph'
import { buildFlaggedGroups } from '../lib/correlation'
import { useAnalysisDetail } from '../lib/useAnalysisDetail'
import { RESULT_TONE, type CorrelationEdge, type ReconResult, type ReconRow, type RecordRef, type Transaction, type TxStatus, type EventType } from '../data/types'

const panel = 'rounded-md border border-line bg-panel p-4'
const input = 'rounded border border-line bg-page px-3 py-2 text-sm'
function Button({ children, onClick, disabled = false, type = 'button' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit'
}) {
  const busy = useApp(s => s.busy)
  return <button type={type} disabled={disabled || busy} onClick={onClick}
    className="rounded border border-line bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent disabled:cursor-not-allowed disabled:opacity-40 hover:brightness-95">{children}</button>
}
function Empty({ children }: { children: ReactNode }) {
  return <div className={panel + ' text-sm text-muted'}>{children}</div>
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
function Table({ data, columns, onSelect, selected }: {
  data: Row[]; columns: [string, string][]; onSelect?: (row: Row) => void; selected?: (row: Row) => boolean
}) {
  const [page, setPage] = useState(0)
  const size = 100
  const pages = Math.max(1, Math.ceil(data.length / size))
  const current = Math.min(page, pages - 1)
  if (!data.length) return <Empty>No results available yet.</Empty>
  return <div className="overflow-auto rounded-md border border-line bg-panel">
    <table className="w-full text-left text-xs"><thead className="bg-thead text-dim"><tr>
      {columns.map(([key, label]) => <th key={key} className="px-3 py-2 font-semibold">{label}</th>)}
      {onSelect && <th className="px-3 py-2">Details</th>}
    </tr></thead><tbody>{data.slice(current * size, (current + 1) * size).map((row, index) =>
      <tr key={current * size + index} className={'border-t border-line ' + (selected?.(row) ? 'bg-accent-soft' : '')}>
        {columns.map(([key]) => <td key={key} className="max-w-xs break-words px-3 py-2 font-mono">{display(row[key])}</td>)}
        {onSelect && <td className="px-3 py-2"><button className="text-accent underline" onClick={() => onSelect(row)}>View</button></td>}
      </tr>)}</tbody></table>
    {pages > 1 && <div className="flex items-center gap-3 border-t border-line p-2 text-xs">
      <button disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
      <span>Page {current + 1} of {pages} · {data.length} results</span>
      <button disabled={current + 1 === pages} onClick={() => setPage(current + 1)}>Next</button>
    </div>}
  </div>
}

export function CasesScreen() {
  const cases = useApp(s => s.cases)
  const [name, setName] = useState('')
  const [examiner, setExaminer] = useState('')
  const [filter, setFilter] = useState('')
  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (await useApp.getState().createCase(name, examiner)) { setName(''); setExaminer('') }
  }
  return <div className="space-y-4">
    <form className={panel + ' flex flex-wrap items-end gap-3'} onSubmit={create}>
      <label className="flex flex-col gap-1 text-xs">Case name<input className={input} required value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="flex flex-col gap-1 text-xs">Examiner<input className={input} required value={examiner} onChange={e => setExaminer(e.target.value)} /></label>
      <Button type="submit" disabled={!name.trim() || !examiner.trim()}>Create case</Button>
      <Button onClick={() => { void useApp.getState().refresh() }}>Refresh cases</Button>
    </form>
    <input aria-label="Filter cases" className={input} placeholder="Filter cases…" value={filter} onChange={e => setFilter(e.target.value)} />
    <Table data={cases.filter(c => (c.name + c.examiner + c.id).toLowerCase().includes(filter.toLowerCase())).map(c => ({ ...c }))}
      columns={[['name', 'Case'], ['examiner', 'Examiner'], ['opened', 'Created'], ['files', 'Files'], ['status', 'Status']]}
      onSelect={row => { void useApp.getState().openCase(String(row.id)) }} />
  </div>
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
export function ReconciliationScreen() {
  const data = useApp(s => s.data)
  const [filter, setFilter] = useState('')
  const [detail, setDetail] = useState<Row | null>(null)
  const loaded = useAnalysisDetail(data?.case.case_id, 'comparison', detail ?? undefined, data?.analysis.reconciliation?.details_deferred === true, detail ? String(detail.field) : undefined)
  useEffect(() => { setDetail(null) }, [data?.case.case_id, data?.run?.run_id])
  const expanded = useApp(s => s.expandedGroups)
  const groups = useMemo(() => graphData(data), [data])
  const all = rows(data?.analysis.reconciliation?.rows)
  const counts = Object.keys(RESULT_TONE).map(result => [result, all.filter(r => r.result === result).length] as const)
  return <div className="space-y-4">
    <div className="grid grid-cols-6 gap-2">{counts.map(([result, count]) => <div key={result} className={panel}><p className="font-mono text-xl">{count}</p><Badge tone={RESULT_TONE[result as ReconResult]}>{result}</Badge></div>)}</div>
    <label className="flex items-center gap-2 text-xs">Filter result<select className={input} value={filter} onChange={e => setFilter(e.target.value)}><option value="">All results</option>{counts.map(([r]) => <option key={r}>{r}</option>)}</select></label>
    <Table data={all.filter(r => !filter || r.result === filter)} columns={[['record_id', 'Record'], ['field', 'Field'], ['log_display', 'Log-derived'], ['phys_display', 'Physical'], ['result', 'Result'], ['rule_id', 'Rule']]} onSelect={setDetail} />
    {detail && <div className="space-y-2"><Button onClick={() => useApp.getState().openRecord(String(detail.record_id))}>Open record history</Button>{loaded.detail ? <><ProvenanceLinks value={loaded.detail.provenance} /><Detail value={loaded.detail} title="Comparison values, rule and source provenance" /></> : <p role="status" className="text-sm text-muted">{loaded.error ?? 'Loading comparison…'}</p>}</div>}
    {groups.map(group => <div key={group.id} className="space-y-2"><Button onClick={() => useApp.getState().toggleGroup(group.id)}>{expanded.includes(group.id) ? 'Hide' : 'Show'} correlation graph · {group.records.length} records</Button>{expanded.includes(group.id) && <CorrelationGraph group={group} />}</div>)}
    {data?.analysis.reconciliation?.coverage && <Detail value={data.analysis.reconciliation.coverage} title="Coverage and limits" />}
  </div>
}

export function GapsScreen() {
  const data = useApp(s => s.data)
  const [detail, setDetail] = useState<Row | null>(null)
  const findings = data?.findings ?? []
  return <div className="space-y-4">
    <Table data={findings} columns={[['rule_id', 'Rule'], ['severity', 'Severity'], ['subject', 'Subject'], ['description', 'Finding']]} onSelect={setDetail} />
    <Table data={data?.tables.warnings ?? []} columns={[['stage', 'Stage'], ['code', 'Code'], ['message', 'Extraction warning'], ['evidence_id', 'Evidence']]} onSelect={setDetail} />
    {data?.analysis.grouping?.coverage && <Detail value={data.analysis.grouping.coverage} title="Binary log coverage" />}
    {detail && <><ProvenanceLinks value={detail.provenance} /><Detail value={detail} title="Finding context and provenance" /></>}
  </div>
}

export function ProvenanceScreen() {
  const data = useApp(s => s.data)
  const selected = useApp(s => s.selectedTool)
  const [stream, setStream] = useState('stdout')
  const [preview, setPreview] = useState<{ text: string; truncated: boolean; sha256?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const toolRuns = data?.tables.tool_runs ?? []
  const current = toolRuns.find(t => t.tool_run_id === selected) ?? toolRuns[0]
  useEffect(() => { setPreview(null) }, [current?.tool_run_id, stream, data?.case.case_id])
  const read = async () => {
    if (!current || !data) return
    setLoading(true)
    try { setPreview(await request('read_tool_output', { case_id: data.case.case_id, run_id: current.tool_run_id, stream })) }
    catch (error) { useApp.getState().setError(error) }
    finally { setLoading(false) }
  }
  return <div className="space-y-4">
    <Table data={toolRuns} columns={[['tool_name', 'Utility'], ['tool_version', 'Version'], ['status', 'Status'], ['exit_code', 'Exit'], ['evidence_id', 'Evidence'], ['started_at', 'Started']]} onSelect={r => useApp.getState().selectTool(String(r.tool_run_id))} selected={r => r.tool_run_id === current?.tool_run_id} />
    {current && <><Detail value={current} title="Command, executable hash and raw output hashes" />
      <div className="flex items-center gap-3"><select aria-label="Output stream" className={input} value={stream} onChange={e => setStream(e.target.value)}><option>stdout</option><option>stderr</option></select>
        <Button disabled={loading} onClick={() => { void read() }}>{loading ? 'Loading…' : 'Read raw output'}</Button></div>
      {preview && <div className={panel}><p className="mb-2 break-all font-mono text-xs">SHA-256: {preview.sha256 ?? 'No output recorded'}{preview.truncated ? ' · Preview limited to 256 KiB' : ''}</p>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{preview.text || '(empty output)'}</pre></div>}</>}
  </div>
}

export function ReportScreen() {
  const state = useApp()
  const [path, setPath] = useState('')
  const choose = async () => {
    try {
      const chosen = await pickExportPath(state.reportFormat)
      if (chosen) setPath(state.reportFormat === 'CSV' ? chosen + '/factumdb-' + state.data?.case.case_id + '-' + Date.now() : chosen)
    } catch (error) { state.setError(error) }
  }
  return <div className="space-y-4">
    <div className={panel}><p className="text-sm font-semibold">Export saved analysis</p><p className="mt-2 text-xs text-muted">JSON contains exact tagged values and all stored case tables. CSV produces a new folder with evidence, tool runs, extracted rows, log events, warnings and reconciliation. Existing exports are never overwritten.</p></div>
    {!state.pipelineComplete && <Empty>Complete the pipeline before exporting this case.</Empty>}
    <form className={panel + ' flex flex-wrap items-end gap-3'} onSubmit={e => { e.preventDefault(); void state.exportCase(path) }}>
      <label className="flex flex-col gap-1 text-xs">Format<select className={input} value={state.reportFormat} onChange={e => { state.setFormat(e.target.value); setPath('') }}><option>JSON</option><option>CSV</option></select></label>
      <label className="flex min-w-72 flex-1 flex-col gap-1 text-xs">{state.reportFormat === 'JSON' ? 'New JSON file path' : 'New CSV folder path'}<input className={input} required value={path} onChange={e => setPath(e.target.value)} /></label>
      <Button disabled={!state.pipelineComplete} onClick={() => { void choose() }}>Choose destination</Button>
      <Button type="submit" disabled={!state.pipelineComplete || !path.trim()}>Export</Button>
    </form>
    {state.data && <div className={panel + ' text-xs'}>{Object.entries(state.data.tables).map(([table, values]) => <p key={table} className="mb-1">{table.replaceAll('_', ' ')}: {state.data?.table_counts?.[table] ?? values.length}</p>)}</div>}
  </div>
}

export function SettingsScreen() {
  const settings = useApp(s => s.settings)
  const [draft, setDraft] = useState<ToolSettings | null>(null)
  useEffect(() => { setDraft(settings?.tools ?? null) }, [settings])
  if (!settings || !draft) return <Empty>Connect to the desktop backend to load settings.</Empty>
  const names: [keyof Omit<ToolSettings, 'include_deleted'>, string][] = [
    ['innochecksum_path', 'innochecksum executable'], ['ibd2sdi_path', 'ibd2sdi executable'],
    ['ibd2sql_path', 'ibd2sql Python script'], ['mysqlbinlog_path', 'mysqlbinlog executable'], ['python_path', 'Python executable for ibd2sql'],
  ]
  return <form className={panel + ' max-w-3xl space-y-4'} onSubmit={e => { e.preventDefault(); void useApp.getState().configure(draft) }}>
    <p className="break-all text-xs">Case storage: {settings.workspace}</p>
    <p className="text-xs text-muted">{settings.bundled_tools && Object.keys(settings.bundled_tools).length ? 'Bundled tools are ready to use. You can select other versions for your evidence.' : 'Provide the MySQL utilities and ibd2sql script before running extraction.'} Paths are saved locally; tool versions and hashes are recorded when a tool runs.</p>
    {names.map(([key, label]) => <label key={key} className="flex flex-col gap-1 text-xs">{label}<input className={input} required={key !== 'ibd2sql_path'} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.include_deleted} onChange={e => setDraft({ ...draft, include_deleted: e.target.checked })} />Include deleted physical rows</label>
    <Button type="submit">Save tool settings</Button>
    {settings.bundled_tools && Object.keys(settings.bundled_tools).length > 0 && <Button type="button" onClick={() => { const restored = { ...draft, ...settings.bundled_tools }; setDraft(restored); void useApp.getState().configure(restored) }}>Use bundled tools</Button>}
  </form>
}
