import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Badge } from '../components/Badge'
import { StatusMessage } from '../components/StatusMessage'
import { navigationButton } from '../components/buttonStyles'
import { TablePagination } from '../components/TablePagination'
import { canonical, compareText, groupFindings, groupWarnings, warningContext, type FindingGroup, type WarningGroup } from '../lib/findingGroups'
import { display, object, rows, type CaseData, type Row } from '../lib/backend'
import { useTablePage } from '../lib/useTablePage'
import { useApp } from '../store'
import { useScreenQuery, useNextPage, type ScreenPage } from '../lib/useScreenQuery'
import { LoadingPanel, QueryError } from '../components/LoadingPanel'
import { CoverageDetails } from '../components/CoverageDetails'
import { RuleCatalogue } from '../components/RuleCatalogue'

type Column<T> = { title: string; render: (value: T) => ReactNode }
const cell = 'px-3 py-2 align-top'
const sourceButton = navigationButton

function ToolLinks({ ids, data }: { ids: string[]; data: CaseData }) {
  const busy = useApp(state => state.busy)
  const valid = new Set((data.tables.tool_runs ?? []).map(run => String(run.tool_run_id)))
  return <div className="flex flex-wrap gap-2">{ids.filter(id => !data.tables.tool_runs || valid.has(id)).map(id => <button key={id} type="button" disabled={busy} className={sourceButton} onClick={() => {
    useApp.getState().selectTool(id); useApp.getState().go('prov')
  }}>Inspect source tool run · {id.slice(0, 8)}</button>)}</div>
}

function Context({ value }: { value: Row }) {
  return <dl className="space-y-1 text-xs">{Object.keys(value).sort(compareText).map(key => <div key={key} className="flex flex-wrap gap-x-2">
    <dt className="text-muted">{key.replaceAll('_', ' ')}:</dt><dd className="break-all">{display(value[key])}</dd>
  </div>)}</dl>
}

function Entries({ entries, columns, groupId, name, total }: { entries: Row[]; columns: Column<Row>[]; groupId: string; name: string; total?: number }) {
  const [page, setPage] = useTablePage(`gaps:entries:${groupId}`)
  const current = Math.min(page, Math.max(0, Math.ceil((total ?? entries.length) / 100) - 1))
  return <div className="overflow-auto rounded border border-line bg-panel">
    <table className="w-full text-left text-xs"><thead className="bg-thead text-dim"><tr>{columns.map(column => <th key={column.title} className="px-3 py-2 font-semibold">{column.title}</th>)}</tr></thead>
      <tbody>{(total === undefined ? entries.slice(current * 100, (current + 1) * 100) : entries).map((entry, index) => <tr key={current * 100 + index} className="border-t border-line">{columns.map(column => <td key={column.title} className={cell}>{column.render(entry)}</td>)}</tr>)}</tbody>
    </table>
    <TablePagination page={current} count={total ?? entries.length} onPage={setPage} label="occurrences" name={`${name} findings pagination`} />
  </div>
}

function Groups<T extends { id: string }>({ groups, columns, tableKey, expand, action, empty, total }: {
  groups: T[]; columns: Column<T>[]; tableKey: string; expand: (group: T) => ReactNode; action: string; empty: string; total?: number
}) {
  const [page, setPage] = useTablePage(`gaps:groups:${tableKey}`)
  const [expanded, setExpanded] = useState<string | null>(null)
  const current = Math.min(page, Math.max(0, Math.ceil((total ?? groups.length) / 100) - 1))
  if (!groups.length) return <StatusMessage>{empty}</StatusMessage>
  return <div className="overflow-auto rounded-md border border-line bg-panel">
    <table className="w-full text-left text-xs"><thead className="bg-thead text-dim"><tr>{columns.map(column => <th key={column.title} className="px-3 py-2 font-semibold">{column.title}</th>)}<th className="px-3 py-2 font-semibold">Details</th></tr></thead>
      <tbody>{(total === undefined ? groups.slice(current * 100, (current + 1) * 100) : groups).map(group => <Fragment key={group.id}>
        <tr className={'border-t border-line ' + (expanded === group.id ? 'bg-accent-soft' : '')}>{columns.map(column => <td key={column.title} className={cell}>{column.render(group)}</td>)}
          <td className={cell}><button type="button" aria-expanded={expanded === group.id} className="inline-flex items-center gap-1 whitespace-nowrap text-accent" onClick={() => setExpanded(expanded === group.id ? null : group.id)}>
            <span className="underline">{expanded === group.id ? 'Hide' : 'View'} {action}</span><span aria-hidden="true" className="text-[16px] leading-none">{expanded === group.id ? '▴' : '▾'}</span>
          </button></td>
        </tr>
        {expanded === group.id && <tr className="border-t border-line bg-thead"><td colSpan={columns.length + 1} className="p-3">{expand(group)}</td></tr>}
      </Fragment>)}</tbody>
    </table>
    <TablePagination page={current} count={total ?? groups.length} onPage={setPage} label="groups" name={`${tableKey} groups pagination`} />
  </div>
}

function FindingEntries({ group, data }: { group: FindingGroup; data: CaseData }) {
  const [page] = useTablePage(`gaps:entries:findings:${group.id}`)
  const legacy = group.entries.length > 0
  const payload = { kind: 'findings', bucket: group.id, offset: page * 100, limit: 100 }
  const query = useScreenQuery<ScreenPage>('get_screen_page', payload, 'gaps', !legacy)
  useNextPage(query.value, payload, 'gaps')
  if (!legacy && !query.value) return <LoadingPanel error={query.error} retry={query.retry} label="Loading findings" />
  const entries = legacy ? group.entries : query.value?.items ?? []
  const ids = [...new Set(entries.flatMap(entry => rows(entry.provenance).map(ref => String(ref.tool_run_id ?? '')).filter(Boolean)))]
  return <div className="space-y-3">
    <QueryError error={query.error} retry={query.retry} />
    <p className="text-xs text-ink">{group.explanation}</p>
    {group.service && <p className="text-xs text-muted">Analysis stage: {group.service}</p>}
    <ToolLinks ids={legacy ? group.toolRunIds : ids} data={data} />
    <Entries entries={entries} total={legacy ? undefined : query.value?.total} groupId={`findings:${group.id}`} name={group.rule} columns={[
      { title: 'Subject', render: entry => { const subject = object(entry.subject); return <span className="break-all"><span className="text-muted">{display(subject.kind)} · </span><span className="font-mono">{display(subject.id)}</span></span> } },
      { title: 'Finding', render: entry => display(entry.description) },
      { title: 'Context', render: entry => <Context value={object(entry.context)} /> },
      { title: 'Sources', render: entry => <div className="space-y-1">{rows(entry.provenance).map((ref, index) => <p key={index} className="break-all font-mono">{display(ref.source_file)}{ref.log_position != null && ` · position ${display(ref.log_position)}`}{ref.row_index != null && ` · row ${display(ref.row_index)}`}</p>)}</div> },
    ]} />
  </div>
}

function WarningEntries({ group, data }: { group: WarningGroup; data: CaseData }) {
  const [page] = useTablePage(`gaps:entries:warnings:${group.id}`)
  const legacy = group.entries.length > 0
  const payload = { kind: 'warning_entries', bucket: group.id, offset: page * 100, limit: 100 }
  const query = useScreenQuery<ScreenPage>('get_screen_page', payload, 'gaps', !legacy)
  useNextPage(query.value, payload, 'gaps')
  if (!legacy && !query.value) return <LoadingPanel error={query.error} retry={query.retry} label="Loading extraction warnings" />
  return <div className="space-y-3">
    <QueryError error={query.error} retry={query.retry} />
    <ToolLinks ids={group.toolRunId ? [group.toolRunId] : []} data={data} />
    <Entries entries={legacy ? group.entries : query.value?.items ?? []} total={legacy ? undefined : query.value?.total} groupId={`warnings:${group.id}`} name={group.code} columns={[
      { title: 'Warning', render: entry => display(entry.message) },
      { title: 'Context', render: entry => <Context value={warningContext(entry)} /> },
      { title: 'Recorded', render: entry => display(entry.created_at) },
      { title: 'Warning ID', render: entry => <span className="break-all font-mono">{display(entry.warning_id)}</span> },
    ]} />
  </div>
}

export function GapsScreen() {
  const data = useApp(state => state.data)
  const [findingPage] = useTablePage('gaps:groups:findings')
  const [warningPage] = useTablePage('gaps:groups:warnings')
  const legacy = !!data?.findings.length || Array.isArray(data?.tables.warnings)
  const findingQuery = useScreenQuery<ScreenPage<FindingGroup> & { counts: Record<string, number> }>('get_screen_page', { kind: 'finding_groups', offset: findingPage * 100, limit: 100 }, 'gaps', !legacy)
  const warningQuery = useScreenQuery<ScreenPage<WarningGroup>>('get_screen_page', { kind: 'warning_groups', offset: warningPage * 100, limit: 100 }, 'gaps', !legacy)
  useNextPage(findingQuery.value,{kind:'finding_groups',offset:findingPage*100,limit:100},'gaps')
  useNextPage(warningQuery.value,{kind:'warning_groups',offset:warningPage*100,limit:100},'gaps')
  const [summary,setSummary]=useState<{caseId:string;counts?:Record<string,number>;warnings?:number}>()
  const caseId=data?.case.case_id
  useEffect(()=>{
    if(caseId && (findingQuery.value || warningQuery.value)) setSummary(previous=>({caseId,
      counts:findingQuery.value?.counts ?? (previous?.caseId===caseId ? previous.counts : undefined),
      warnings:warningQuery.value?.total ?? (previous?.caseId===caseId ? previous.warnings : undefined)}))
  },[caseId,findingQuery.value,warningQuery.value])
  const findingCounts=findingQuery.value?.counts ?? (summary?.caseId===data?.case.case_id ? summary?.counts : undefined)
  const warningCount=warningQuery.value?.total ?? (summary?.caseId===data?.case.case_id ? summary?.warnings : undefined)
  const localFindings = useMemo(() => groupFindings(data?.findings ?? [], data?.finding_rules), [data?.findings, data?.finding_rules])
  const localWarnings = useMemo(() => groupWarnings(data?.tables.warnings ?? []), [data?.tables.warnings])
  const findings = legacy ? localFindings : findingQuery.value?.items ?? []
  const warnings = legacy ? localWarnings : warningQuery.value?.items ?? []
  const evidence = useMemo(() => new Map((data?.tables.evidence_files ?? []).map(file => [String(file.evidence_id), String(file.filename)])), [data?.tables.evidence_files])
  if (!data) return <StatusMessage>Open a case to view gaps and warnings.</StatusMessage>
  const scope = canonical([data.case.case_id, data.run?.run_id ?? null])
  return <div className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-3">{[
      ['Warning groups', legacy ? findings.filter(group => group.severity === 'warning').length : findingCounts?.warning],
      ['Notice groups', legacy ? findings.filter(group => group.severity === 'notice').length : findingCounts?.notice],
      ['Extraction warning groups', legacy ? warnings.length : warningCount],
    ].map(([label, count]) => <div key={label} className="rounded-md border border-line bg-panel p-4"><p className="text-xs text-muted">{label}</p><p className="mt-1 font-mono text-xl font-semibold tabular-nums">{count === undefined ? '—' : Number(count).toLocaleString()}</p></div>)}</div>
    <QueryError error={findingQuery.error} retry={findingQuery.retry} />
    <QueryError error={warningQuery.error} retry={warningQuery.retry} />
    <p className="text-xs text-muted">Grouped by rule. Occurrences count original findings; distinct subjects can overlap between groups. These counts do not represent separate attacks or root causes.</p>
    {!legacy && !findingQuery.value ? <LoadingPanel error={findingQuery.error} retry={findingQuery.retry} label="Loading finding groups" /> : <Groups key={`findings:${scope}`} total={legacy ? undefined : findingQuery.value?.total} groups={findings} tableKey="findings" action="findings" empty="No warning or notice findings available." columns={[
      { title: 'Rule', render: group => <span className="font-mono">{group.rule}</span> },
      { title: 'Finding', render: group => group.title },
      { title: 'Severity', render: group => <Badge tone={group.severity === 'warning' ? 'warn' : group.severity === 'notice' ? 'info' : 'neutral'}>{group.severity}</Badge> },
      { title: 'Occurrences', render: group => <span className="tabular-nums">{group.occurrences.toLocaleString()}</span> },
      { title: 'Distinct subjects', render: group => <span className="tabular-nums">{group.subjects.toLocaleString()}</span> },
    ]} expand={group => <FindingEntries group={group} data={data} />} />}
    <h2 className="text-xs font-semibold">Extraction warnings</h2>
    <p className="text-xs text-muted">Grouped by warning code, evidence file, and tool run. Occurrences include all stored warnings, including those from earlier runs.</p>
    {!legacy && !warningQuery.value ? <LoadingPanel error={warningQuery.error} retry={warningQuery.retry} label="Loading warning groups" /> : <Groups key={`warnings:${scope}`} total={legacy ? undefined : warningQuery.value?.total} groups={warnings} tableKey="warnings" action="warnings" empty="No extraction warnings available." columns={[
      { title: 'Code', render: group => <span className="font-mono">{group.code}</span> },
      { title: 'Evidence', render: group => group.evidenceId ? evidence.get(group.evidenceId) ?? group.evidenceId : 'Case-wide' },
      { title: 'Tool run', render: group => <span className="break-all font-mono">{group.toolRunId || 'Not recorded'}</span> },
      { title: 'Occurrences', render: group => <span className="tabular-nums">{group.occurrences.toLocaleString()}</span> },
    ]} expand={group => <WarningEntries group={group} data={data} />} />}
    {data.analysis.grouping?.coverage && <details className="rounded-md border border-line bg-panel p-4"><summary className="cursor-pointer text-xs font-medium">Binary log coverage</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify(data.analysis.grouping.coverage, null, 2)}</pre></details>}
    {!legacy && <CoverageDetails kind="grouping" screen="gaps" title="Binary log coverage" />}
    <RuleCatalogue />
  </div>
}
