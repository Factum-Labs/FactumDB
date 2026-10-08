import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useApp } from '../store'
import { display, object, request, rows, type Attempt, type Row } from '../lib/backend'

const STAGES = [
  ['verify_evidence', 'Verified working copies'],
  ['validate_pages', 'InnoDB page validation'],
  ['extract_schema', 'Schema extraction'],
  ['extract_physical_rows', 'Physical-row extraction'],
  ['decode_binary_logs', 'Binary-log decoding'],
  ['normalize_evidence', 'Normalization'],
  ['group_transactions', 'Transaction grouping'],
  ['correlate_records', 'Record correlation'],
  ['reconstruct_state', 'State reconstruction'],
  ['reconcile_records', 'Reconciliation'],
] as const

function duration(attempt?: Attempt): string {
  if (!attempt?.finished_at) return '—'
  const elapsed = Date.parse(attempt.finished_at) - Date.parse(attempt.started_at)
  return Number.isFinite(elapsed) && elapsed >= 0 ? `${(elapsed / 1000).toFixed(1)} s` : '—'
}

function Action({ children, onClick, disabled, primary = false }: {
  children: ReactNode; onClick: () => void; disabled?: boolean; primary?: boolean
}) {
  return <button type="button" onClick={onClick} disabled={disabled}
    className={'h-[26px] rounded px-2.5 text-[11.5px] disabled:cursor-not-allowed ' + (primary
      ? 'bg-accent font-medium text-white hover:bg-accent-dark disabled:opacity-40 disabled:hover:bg-accent'
      : 'border border-line-input bg-panel text-ink hover:bg-page disabled:text-dimmer disabled:hover:bg-panel')}>
    {children}
  </button>
}

const dotColors: Record<string, string> = {
  succeeded: 'bg-ok', warning: 'bg-amber', failed: 'bg-danger', running: 'bg-accent animate-pulse',
  pending: 'bg-faint', skipped: 'bg-faint', cancelled: 'bg-amber',
}

function StageRow({ number, label, status, summary, attempt, attempts = [] }: {
  number: number; label: string; status: string; summary: string; attempt?: Attempt; attempts?: Attempt[]
}) {
  return <li className={'border-t border-line-soft ' + (status === 'running' ? 'bg-accent-soft/50' : '')}>
    <div className="grid grid-cols-[26px_7px_minmax(0,1fr)_64px] items-center gap-x-2.5 px-3 py-[7px] sm:grid-cols-[26px_7px_minmax(0,1fr)_minmax(128px,28%)_64px]">
      <span className="col-start-1 row-start-1 font-mono text-[11px] text-dimmer">{String(number).padStart(2, '0')}</span>
      <span aria-hidden="true" className={'col-start-2 row-start-1 h-[7px] w-[7px] rounded-full ' + (status === 'pending' || status === 'skipped' ? 'border border-dim' : dotColors[status] ?? 'bg-faint')} />
      <span className={'col-start-3 row-start-1 text-[12px] ' + (status === 'pending' || status === 'skipped' ? 'text-dim' : '')}>{label}<span className="sr-only">: {status}</span></span>
      <span className="col-start-3 row-start-2 mt-1 text-[11px] text-muted sm:col-start-4 sm:row-start-1 sm:mt-0">{summary}</span>
      <span className="col-start-4 row-start-1 text-right font-mono text-[11px] text-dimmer sm:col-start-5">{status === 'running' ? 'Running' : duration(attempt)}</span>
    </div>
    {attempt?.skip_reason && <p className="px-3 pb-2 pl-[65px] text-[11px] text-muted">{attempt.skip_reason}</p>}
    {attempt?.error_message && <p role="alert" className="break-words px-3 pb-2 pl-[65px] text-[11px] text-danger">{attempt.error_code}: {attempt.error_message}</p>}
    {attempts.length > 1 && <details className="px-3 pb-2 pl-[65px] text-[11px] text-muted">
      <summary className="cursor-pointer">Previous attempts</summary>
      {attempts.slice(0, -1).map(previous => <p key={previous.number} className="mt-2">
        Attempt {previous.number} · {previous.status} · {previous.item_count} items · {duration(previous)}
        {previous.error_message ? ` · ${previous.error_message}` : ''}
        {previous.skip_reason ? ` · ${previous.skip_reason}` : ''}
      </p>)}
    </details>}
  </li>
}

type Output = { text: string; truncated: boolean }
function ToolLog({ tool, caseId }: { tool: Row; caseId: string }) {
  const [output, setOutput] = useState<{ stdout?: Output; stderr?: Output; error?: string }>({})
  const id = String(tool.tool_run_id)
  const finished = typeof tool.finished_at === 'string'
  const hasStdout = typeof tool.stdout_path === 'string'
  const hasStderr = typeof tool.stderr_path === 'string' && Number(tool.stderr_size_bytes) > 0
  useEffect(() => {
    if (!finished) return
    let active = true
    const streams = [hasStdout ? 'stdout' : null, hasStderr ? 'stderr' : null].filter((s): s is string => !!s)
    void Promise.all(streams.map(async stream => {
      try {
        const preview = await request<Output>('read_tool_output', { case_id: caseId, run_id: id, stream })
        if (active) setOutput(current => ({ ...current, [stream]: preview }))
      } catch (error) {
        if (active) setOutput(current => ({ ...current, error: error instanceof Error ? error.message : String(error) }))
      }
    }))
    return () => { active = false }
  }, [caseId, id, finished, hasStdout, hasStderr])
  const args = Array.isArray(tool.arguments) ? tool.arguments.map(display).join(' ') : ''
  return <div className="mb-3 break-words font-mono text-[11px] leading-[1.65]">
    <p className="text-faint">$ {display(tool.tool_name)} {args}</p>
    <p>Version {display(tool.tool_version)} · {display(tool.status)}{tool.exit_code != null ? ` · exit ${display(tool.exit_code)}` : ''}</p>
    {(['stdout', 'stderr'] as const).map(stream => output[stream] && <div key={stream}>
      {stream === 'stderr' && <p className="text-amber">stderr:</p>}
      <pre className="whitespace-pre-wrap break-words">{output[stream].text.slice(0, 4000)}</pre>
      {(output[stream].truncated || output[stream].text.length > 4000) && <p className="text-faint">Output preview shortened. Inspect the source tool run for more.</p>}
    </div>)}
    {output.error && <p className="text-amber">Output unavailable: {output.error}</p>}
    <button type="button" className="text-accent-light underline" onClick={() => {
      useApp.getState().selectTool(id); useApp.getState().go('prov')
    }}>Inspect source tool run</button>
  </div>
}

function ExecutionLog({ tools, caseId }: { tools: Row[]; caseId: string }) {
  const viewport = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const scrollArea = viewport.current
    const logContent = content.current
    if (!scrollArea || !logContent) return
    let frame: number | undefined
    const followOutput = () => {
      if (frame !== undefined) cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        scrollArea.scrollTop = scrollArea.scrollHeight
        frame = undefined
      })
    }
    // Output previews arrive asynchronously inside ToolLog, independently of
    // the pipeline stage updates. Observe both those edits and resized panels.
    const mutations = new MutationObserver(followOutput)
    mutations.observe(logContent, { childList: true, subtree: true, characterData: true })
    const sizes = new ResizeObserver(followOutput)
    sizes.observe(scrollArea)
    sizes.observe(logContent)
    followOutput()
    return () => {
      mutations.disconnect()
      sizes.disconnect()
      if (frame !== undefined) cancelAnimationFrame(frame)
    }
  }, [caseId])
  return <section aria-labelledby="execution-heading" className="flex min-h-0 flex-col overflow-hidden rounded-md bg-ink px-3 py-[11px] text-line lg:flex-1">
    <h2 id="execution-heading" className="mb-2 shrink-0 text-[10px] font-semibold uppercase tracking-[.07em] text-dim">Execution log</h2>
    <div ref={viewport} tabIndex={0} aria-label="Tool execution output" className="scroll-dark min-h-0 max-h-[min(330px,50dvh)] overflow-auto pr-2 lg:max-h-none lg:flex-1">
      <div ref={content} className="min-w-0 [overflow-wrap:anywhere]">
        {!tools.length && <p className="font-mono text-[11px] leading-[1.65] text-dim">Tool commands and output will appear as analysis runs.</p>}
        {tools.length > 20 && <p className="mb-3 text-[11px]">Showing the latest 20 tool runs. Earlier runs are available in provenance.</p>}
        {tools.slice(-20).map(tool => <ToolLog key={String(tool.tool_run_id)} caseId={caseId} tool={tool} />)}
      </div>
    </div>
  </section>
}

export function PipelineScreen() {
  const state = useApp()
  const data = state.data
  if (!data) return <div className="rounded-md border border-line bg-panel p-4 text-sm text-muted">Open or create a case first.</div>
  const run = data.run
  const evidence = data.tables.evidence_files ?? []
  const verified = evidence.filter(e => e.verification_status === 'verified').length
  const hashes = evidence.filter(e => !!e.source_sha256).length
  const hasEvidence = evidence.some(e => e.kind === 'ibd' || e.kind === 'binlog')
  const integrity = data.tables.integrity_results ?? []
  const schemas = data.tables.schemas ?? []
  const transactions = rows(data.analysis.grouping?.transactions)
  const records = rows(data.analysis.correlation?.records)
  const comparisons = rows(data.analysis.reconciliation?.rows)
  const coverage = object(data.analysis.grouping?.coverage)
  const gaps = rows(coverage.gaps).length
  const inventories = data.tables.binlog_inventory ?? []
  const missing = new Set(inventories.flatMap(i => Array.isArray(i.missing_files) ? i.missing_files.map(display) : [])).size
  const damaged = integrity.reduce((sum, i) => sum + Number(i.damaged_pages ?? 0), 0)
  const toolRuns = data.tables.tool_runs ?? []
  const failed = run?.stages.find(s => s.status === 'failed')
  const locked = state.busy || !!run?.stopped || !hasEvidence
  const summaries: Record<string, string> = {
    verify_evidence: `${verified} / ${evidence.length} match`,
    validate_pages: `${integrity.some(i => i.total_pages == null) ? 'Unknown' : integrity.reduce((sum, i) => sum + Number(i.total_pages), 0)} pages, ${damaged} damaged`,
    extract_schema: `${schemas.length} tables, ${data.tables.schema_columns?.length ?? 0} columns`,
    extract_physical_rows: `${data.table_counts?.physical_records ?? data.tables.physical_records?.length ?? 0} rows`,
    decode_binary_logs: `${evidence.filter(e => e.kind === 'binlog').length} logs, ${missing} missing`,
    group_transactions: `${transactions.length} transactions`,
    correlate_records: `${records.length} records linked`,
    reconstruct_state: `${rows(data.analysis.reconstruction?.histories).length} histories`,
    reconcile_records: `${comparisons.length} comparisons`,
  }
  const metrics = [
    { label: 'Evidence files', value: evidence.length },
    { label: 'Verified', value: verified, tone: 'text-ok' },
    { label: 'Tables parsed', value: schemas.length },
    { label: 'Transactions', value: data.analysis.grouping ? transactions.length : '—' },
    { label: 'Records correlated', value: data.analysis.correlation ? records.length : '—' },
    { label: 'Exact matches', value: data.analysis.reconciliation ? comparisons.filter(r => r.result === 'Exact').length : '—', tone: 'text-ok' },
    { label: 'Unresolved', value: data.analysis.reconciliation ? comparisons.filter(r => r.result === 'Unresolved').length : '—' },
    { label: 'Coverage gaps', value: data.analysis.grouping ? gaps : '—', tone: gaps ? 'text-amber' : '' },
  ]
  return <div className="grid min-h-0 max-w-[1240px] items-start gap-4 lg:h-full lg:grid-cols-[minmax(0,1fr)_minmax(280px,400px)] lg:grid-rows-[minmax(0,1fr)]">
    <section aria-labelledby="pipeline-heading" className="min-h-0 min-w-0 overflow-auto rounded-md border border-line bg-panel lg:max-h-full">
      <div className="flex flex-wrap items-center justify-between gap-2.5 px-3 py-[9px]">
        <h2 id="pipeline-heading" className="text-[12px] font-semibold">Processing pipeline</h2>
        <div className="flex flex-wrap gap-2">
          <Action disabled={locked} onClick={() => { void state.runStage() }}>Run stage</Action>
          <Action primary disabled={locked} onClick={() => { void state.runAllStages() }}>Run complete analysis</Action>
        </div>
      </div>
      <ol>
        <StageRow number={1} label="Evidence registration" status={evidence.length ? 'succeeded' : 'pending'} summary={`${evidence.length} files`} />
        <StageRow number={2} label="SHA-256 hashing" status={evidence.length && hashes === evidence.length ? 'succeeded' : 'pending'} summary={`${hashes} hashes`} />
        {STAGES.map(([id, label], index) => {
          const stage = run?.stages.find(s => s.stage === id)
          const attempt = stage?.attempts.at(-1)
          const running = state.runningStage === index
          const status = running ? 'running' : stage?.status ?? 'pending'
          const warning = status === 'succeeded' && ((id === 'validate_pages' && (damaged > 0 || integrity.some(i => i.status !== 'valid'))) || (id === 'decode_binary_logs' && missing > 0) || (id === 'group_transactions' && gaps > 0))
          return <StageRow key={id} number={index + 3} label={label} status={warning ? 'warning' : status}
            summary={running ? 'Processing…' : status === 'succeeded' ? summaries[id] ?? `${attempt?.item_count ?? 0} objects` : status === 'skipped' ? 'Skipped' : status === 'pending' ? 'Pending' : status}
            attempt={attempt} attempts={stage?.attempts} />
        })}
        <StageRow number={13} label="Result persistence & report" status={run?.complete ? 'succeeded' : 'pending'}
          summary={run?.complete ? 'Case database saved · report ready' : 'Pending'} />
      </ol>
      <div className="flex flex-wrap items-center gap-2.5 border-t border-line px-3 py-[9px]">
        <span role="status" className="mr-auto text-[11px] text-muted">{state.stagesDone}/{STAGES.length} analysis stages completed · {run?.complete ? 'Complete' : state.busy ? 'Processing' : run?.stopped ? 'Stopped' : 'Ready'}</span>
        {failed && <Action disabled={state.busy || failed.stage === 'verify_evidence'} onClick={() => { void state.retryPipeline() }}>Retry failed stage</Action>}
        {run?.stopped && <Action disabled={state.busy} onClick={() => { void state.resetPipeline() }}>Start new analysis</Action>}
        {run && !run.stopped && <Action disabled={state.cancelRequested} onClick={() => { void state.cancelPipeline() }}>{state.cancelRequested ? 'Cancellation requested' : 'Cancel at stage boundary'}</Action>}
        {run?.complete && <Action onClick={() => state.go('report')}>Open report</Action>}
      </div>
      {!hasEvidence && <p className="border-t border-line px-4 py-3 text-xs text-muted">Register at least one .ibd or binary log file before analysis. An index alone is insufficient.</p>}
    </section>
    <aside className="flex min-h-0 min-w-0 flex-col gap-3 lg:h-full" aria-label="Analysis summary">
      <dl className="grid shrink-0 grid-cols-2 gap-2">
        {metrics.map(metric => <div key={metric.label} className="rounded-md border border-line bg-panel px-[11px] py-[9px]">
          <dt className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">{metric.label}</dt>
          <dd className={'mt-0.5 font-mono text-[18px] font-semibold ' + (metric.tone ?? 'text-ink')}>{metric.value}</dd>
        </div>)}
      </dl>
      <ExecutionLog tools={toolRuns} caseId={data.case.case_id} />
    </aside>
  </div>
}
