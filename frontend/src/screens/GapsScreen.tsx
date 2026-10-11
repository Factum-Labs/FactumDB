import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { Badge } from '../components/Badge'
import { StatusMessage } from '../components/StatusMessage'
import { navigationButton } from '../components/buttonStyles'
import { TablePagination } from '../components/TablePagination'
import { canonical, compareText, groupFindings, groupWarnings, warningContext, type FindingGroup, type WarningGroup } from '../lib/findingGroups'
import { display, object, rows, type CaseData, type Row } from '../lib/backend'
import { useTablePage } from '../lib/useTablePage'
import { useApp } from '../store'

type Column<T> = { title: string; render: (value: T) => ReactNode }
const cell = 'px-3 py-2 align-top'
const sourceButton = navigationButton

function ToolLinks({ ids, data }: { ids: string[]; data: CaseData }) {
  const busy = useApp(state => state.busy)
  const valid = new Set((data.tables.tool_runs ?? []).map(run => String(run.tool_run_id)))
  return <div className="flex flex-wrap gap-2">{ids.filter(id => valid.has(id)).map(id => <button key={id} type="button" disabled={busy} className={sourceButton} onClick={() => {
    useApp.getState().selectTool(id); useApp.getState().go('prov')
  }}>Inspect source tool run · {id.slice(0, 8)}</button>)}</div>
}

function Context({ value }: { value: Row }) {
  return <dl className="space-y-1 text-xs">{Object.keys(value).sort(compareText).map(key => <div key={key} className="flex flex-wrap gap-x-2">
    <dt className="text-muted">{key.replaceAll('_', ' ')}:</dt><dd className="break-all">{display(value[key])}</dd>
  </div>)}</dl>
}

function Entries({ entries, columns, groupId, name }: { entries: Row[]; columns: Column<Row>[]; groupId: string; name: string }) {
  const [page, setPage] = useTablePage(`gaps:entries:${groupId}`)
  const current = Math.min(page, Math.max(0, Math.ceil(entries.length / 100) - 1))
  return <div className="overflow-auto rounded border border-line bg-panel">
    <table className="w-full text-left text-xs"><thead className="bg-thead text-dim"><tr>{columns.map(column => <th key={column.title} className="px-3 py-2 font-semibold">{column.title}</th>)}</tr></thead>
      <tbody>{entries.slice(current * 100, (current + 1) * 100).map((entry, index) => <tr key={current * 100 + index} className="border-t border-line">{columns.map(column => <td key={column.title} className={cell}>{column.render(entry)}</td>)}</tr>)}</tbody>
    </table>
    <TablePagination page={current} count={entries.length} onPage={setPage} label="occurrences" name={`${name} findings pagination`} />
  </div>
}

function Groups<T extends { id: string }>({ groups, columns, tableKey, expand, action, empty }: {
  groups: T[]; columns: Column<T>[]; tableKey: string; expand: (group: T) => ReactNode; action: string; empty: string
}) {
  const [page, setPage] = useTablePage(`gaps:groups:${tableKey}`)
  const [expanded, setExpanded] = useState<string | null>(null)
  const current = Math.min(page, Math.max(0, Math.ceil(groups.length / 100) - 1))
  if (!groups.length) return <StatusMessage>{empty}</StatusMessage>
  return <div className="overflow-auto rounded-md border border-line bg-panel">
    <table className="w-full text-left text-xs"><thead className="bg-thead text-dim"><tr>{columns.map(column => <th key={column.title} className="px-3 py-2 font-semibold">{column.title}</th>)}<th className="px-3 py-2 font-semibold">Details</th></tr></thead>
      <tbody>{groups.slice(current * 100, (current + 1) * 100).map(group => <Fragment key={group.id}>
        <tr className={'border-t border-line ' + (expanded === group.id ? 'bg-accent-soft' : '')}>{columns.map(column => <td key={column.title} className={cell}>{column.render(group)}</td>)}
          <td className={cell}><button type="button" aria-expanded={expanded === group.id} className="inline-flex items-center gap-1 whitespace-nowrap text-accent" onClick={() => setExpanded(expanded === group.id ? null : group.id)}>
            <span className="underline">{expanded === group.id ? 'Hide' : 'View'} {action}</span><span aria-hidden="true" className="text-[16px] leading-none">{expanded === group.id ? '▴' : '▾'}</span>
          </button></td>
        </tr>
        {expanded === group.id && <tr className="border-t border-line bg-thead"><td colSpan={columns.length + 1} className="p-3">{expand(group)}</td></tr>}
      </Fragment>)}</tbody>
    </table>
    <TablePagination page={current} count={groups.length} onPage={setPage} label="groups" name={`${tableKey} groups pagination`} />
  </div>
}

function FindingEntries({ group, data }: { group: FindingGroup; data: CaseData }) {
  return <div className="space-y-3">
    <p className="text-xs text-ink">{group.explanation}</p>
    {group.service && <p className="text-xs text-muted">Analysis stage: {group.service}</p>}
    <ToolLinks ids={group.toolRunIds} data={data} />
    <Entries entries={group.entries} groupId={`findings:${group.id}`} name={group.rule} columns={[
      { title: 'Subject', render: entry => { const subject = object(entry.subject); return <span className="break-all"><span className="text-muted">{display(subject.kind)} · </span><span className="font-mono">{display(subject.id)}</span></span> } },
      { title: 'Finding', render: entry => display(entry.description) },
      { title: 'Context', render: entry => <Context value={object(entry.context)} /> },
      { title: 'Sources', render: entry => <div className="space-y-1">{rows(entry.provenance).map((ref, index) => <p key={index} className="break-all font-mono">{display(ref.source_file)}{ref.log_position != null && ` · position ${display(ref.log_position)}`}{ref.row_index != null && ` · row ${display(ref.row_index)}`}</p>)}</div> },
    ]} />
  </div>
}

function WarningEntries({ group, data }: { group: WarningGroup; data: CaseData }) {
  return <div className="space-y-3">
    <ToolLinks ids={group.toolRunId ? [group.toolRunId] : []} data={data} />
    <Entries entries={group.entries} groupId={`warnings:${group.id}`} name={group.code} columns={[
      { title: 'Warning', render: entry => display(entry.message) },
      { title: 'Context', render: entry => <Context value={warningContext(entry)} /> },
      { title: 'Recorded', render: entry => display(entry.created_at) },
      { title: 'Warning ID', render: entry => <span className="break-all font-mono">{display(entry.warning_id)}</span> },
    ]} />
  </div>
}

export function GapsScreen() {
  const data = useApp(state => state.data)
  const findings = useMemo(() => groupFindings(data?.findings ?? [], data?.finding_rules), [data?.findings, data?.finding_rules])
  const warnings = useMemo(() => groupWarnings(data?.tables.warnings ?? []), [data?.tables.warnings])
  const evidence = useMemo(() => new Map((data?.tables.evidence_files ?? []).map(file => [String(file.evidence_id), String(file.filename)])), [data?.tables.evidence_files])
  if (!data) return <StatusMessage>Open a case to view gaps and warnings.</StatusMessage>
  const scope = canonical([data.case.case_id, data.run?.run_id ?? null])
  return <div className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-3">{[
      ['Warning groups', findings.filter(group => group.severity === 'warning').length],
      ['Notice groups', findings.filter(group => group.severity === 'notice').length],
      ['Extraction warning groups', warnings.length],
    ].map(([label, count]) => <div key={label} className="rounded-md border border-line bg-panel p-4"><p className="text-xs text-muted">{label}</p><p className="mt-1 font-mono text-xl font-semibold tabular-nums">{Number(count).toLocaleString()}</p></div>)}</div>
    <p className="text-xs text-muted">Grouped by rule. Occurrences count original findings; distinct subjects can overlap between groups. These counts do not represent separate attacks or root causes.</p>
    <Groups key={`findings:${scope}`} groups={findings} tableKey="findings" action="findings" empty="No warning or notice findings available." columns={[
      { title: 'Rule', render: group => <span className="font-mono">{group.rule}</span> },
      { title: 'Finding', render: group => group.title },
      { title: 'Severity', render: group => <Badge tone={group.severity === 'warning' ? 'warn' : group.severity === 'notice' ? 'info' : 'neutral'}>{group.severity}</Badge> },
      { title: 'Occurrences', render: group => <span className="tabular-nums">{group.occurrences.toLocaleString()}</span> },
      { title: 'Distinct subjects', render: group => <span className="tabular-nums">{group.subjects.toLocaleString()}</span> },
    ]} expand={group => <FindingEntries group={group} data={data} />} />
    <h2 className="text-xs font-semibold">Extraction warnings</h2>
    <p className="text-xs text-muted">Grouped by warning code, evidence file, and tool run. Occurrences include all stored warnings, including those from earlier runs.</p>
    <Groups key={`warnings:${scope}`} groups={warnings} tableKey="warnings" action="warnings" empty="No extraction warnings available." columns={[
      { title: 'Code', render: group => <span className="font-mono">{group.code}</span> },
      { title: 'Evidence', render: group => group.evidenceId ? evidence.get(group.evidenceId) ?? group.evidenceId : 'Case-wide' },
      { title: 'Tool run', render: group => <span className="break-all font-mono">{group.toolRunId || 'Not recorded'}</span> },
      { title: 'Occurrences', render: group => <span className="tabular-nums">{group.occurrences.toLocaleString()}</span> },
    ]} expand={group => <WarningEntries group={group} data={data} />} />
    {data.analysis.grouping?.coverage && <details className="rounded-md border border-line bg-panel p-4"><summary className="cursor-pointer text-xs font-medium">Binary log coverage</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify(data.analysis.grouping.coverage, null, 2)}</pre></details>}
  </div>
}
