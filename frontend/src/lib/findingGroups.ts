import { object, rows, type CaseData, type Json, type Row } from './backend'

// Fixed code-unit ordering: grouping never depends on locale or input order.
export const compareText = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0
export function canonical(value: Json | undefined): string {
  if (value === undefined) return 'undefined'
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value !== null && typeof value === 'object') return `{${Object.keys(value).sort(compareText).map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
  return JSON.stringify(value)
}

export interface FindingGroup {
  id: string; rule: string; severity: string; title: string; explanation: string; service: string
  occurrences: number; subjects: number; entries: Row[]; toolRunIds: string[]
}
export interface WarningGroup {
  id: string; code: string; evidenceId: string; toolRunId: string; occurrences: number; entries: Row[]
}

export function groupFindings(findings: Row[], catalogue: CaseData['finding_rules'] = {}): FindingGroup[] {
  const buckets = new Map<string, { rule: string; severity: string; entries: Row[] }>()
  for (const finding of findings) {
    const rule = String(finding.rule_id ?? 'Unknown rule')
    const severity = String(finding.severity ?? 'unknown')
    const id = JSON.stringify([rule, severity])
    const bucket = buckets.get(id) ?? { rule, severity, entries: [] }
    bucket.entries.push(finding)
    buckets.set(id, bucket)
  }
  const rank: Record<string, number> = { warning: 0, notice: 1, info: 2 }
  return [...buckets.entries()].map(([id, bucket]) => {
    const subjects = new Set<string>()
    const toolRuns = new Set<string>()
    const keyed = bucket.entries.map(entry => {
      const subject = object(entry.subject)
      const kind = String(subject.kind ?? '')
      const identity = String(subject.id ?? '')
      subjects.add(JSON.stringify([kind, identity]))
      for (const ref of rows(entry.provenance)) if (typeof ref.tool_run_id === 'string' && ref.tool_run_id) toolRuns.add(ref.tool_run_id)
      return { entry, kind, identity, tie: canonical([entry.context ?? {}, entry.provenance ?? [], entry]) }
    })
    keyed.sort((a, b) => compareText(a.kind, b.kind) || compareText(a.identity, b.identity) || compareText(a.tie, b.tie))
    const definition = catalogue[bucket.rule]
    return { id, rule: bucket.rule, severity: bucket.severity, title: definition?.title ?? bucket.rule,
      explanation: definition?.explanation ?? 'No catalogue explanation is available. Original finding descriptions are preserved below.',
      service: definition?.service ?? '', occurrences: bucket.entries.length, subjects: subjects.size,
      entries: keyed.map(item => item.entry), toolRunIds: [...toolRuns].sort(compareText) }
  }).sort((a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3) || compareText(a.rule, b.rule) || compareText(a.severity, b.severity))
}

export function groupWarnings(warnings: Row[]): WarningGroup[] {
  const buckets = new Map<string, WarningGroup>()
  for (const warning of warnings) {
    const code = String(warning.code ?? 'Unknown warning')
    const evidenceId = String(warning.evidence_id ?? '')
    const toolRunId = String(warning.tool_run_id ?? '')
    const id = JSON.stringify([code, evidenceId, toolRunId])
    const group = buckets.get(id) ?? { id, code, evidenceId, toolRunId, occurrences: 0, entries: [] }
    group.entries.push(warning)
    group.occurrences++
    buckets.set(id, group)
  }
  return [...buckets.values()].map(group => ({ ...group,
    entries: group.entries.map(entry => ({ entry, key: canonical(entry) })).sort((a, b) => compareText(a.key, b.key)).map(item => item.entry),
  })).sort((a, b) => compareText(a.code, b.code) || compareText(a.evidenceId, b.evidenceId) || compareText(a.toolRunId, b.toolRunId))
}

export function warningContext(warning: Row): Row {
  if (typeof warning.context_json === 'string') {
    try { return object(JSON.parse(warning.context_json) as Json) } catch { return { 'Unparsed context': warning.context_json } }
  }
  return object(warning.context)
}
