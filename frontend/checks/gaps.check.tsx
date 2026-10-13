import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { canonical, groupFindings, groupWarnings, warningContext } from '../src/lib/findingGroups'
import { GapsScreen } from '../src/screens/GapsScreen'
import { useApp } from '../src/store'
import type { CaseData, Row } from '../src/lib/backend'

const finding = (rule: string, kind: string, id: string, severity = 'notice', extra: Row = {}): Row => ({
  rule_id: rule, severity, subject: { kind, id }, context: {}, provenance: [], description: `${rule}: ${id}`, ...extra,
})
const input = [
  finding('R-B', 'record', 'a'), finding('R-A', 'record', 'b', 'warning'),
  finding('R-A', 'field', 'a'), finding('R-A', 'record', 'a'),
  finding('R-A', 'record', 'a', 'notice', { context: { z: 'last', a: 'first' } }),
  finding('R-A', 'record', 'b'), finding('R-UNKNOWN', 'case', 'case', 'warning'),
]
const catalogue = { 'R-A': { title: 'Known title', explanation: 'Known explanation', service: 'reconciliation' } }
const expected = groupFindings(input, catalogue)
assert.deepEqual(groupFindings([...input].reverse(), catalogue), expected)
for (let offset = 1; offset < input.length; offset++) assert.deepEqual(groupFindings([...input.slice(offset), ...input.slice(0, offset)], catalogue), expected)
assert.equal(canonical({ z: 1, a: { y: 2, b: 3 } }), canonical({ a: { b: 3, y: 2 }, z: 1 }))
assert.equal(expected.reduce((sum, group) => sum + group.occurrences, 0), input.length)
assert.deepEqual(expected.map(group => [group.rule, group.severity]), [['R-A', 'warning'], ['R-UNKNOWN', 'warning'], ['R-A', 'notice'], ['R-B', 'notice']])
const a = expected.find(group => group.rule === 'R-A' && group.severity === 'notice')!
assert.equal(a.subjects, 3)
assert.equal(a.occurrences, 4)
assert.equal(a.title, 'Known title')
assert.equal(expected[1].title, 'R-UNKNOWN')
assert.deepEqual(groupFindings([]), [])
assert.deepEqual(groupWarnings([]), [])
const preserved = expected.flatMap(group => group.entries).map(canonical).sort()
assert.deepEqual(preserved, input.map(canonical).sort())
const warning = (id: string, evidence = 'e1', run = 't1'): Row => ({ warning_id: id, code: 'DECODE', evidence_id: evidence, tool_run_id: run, message: 'Original message', context_json: '{"column":"payload"}' })
const warnings = [warning('w2'), warning('w1'), warning('w3', 'e2'), warning('w4', 'e1', 't2'), warning('w4', 'e1', 't2')]
const warningGroups = groupWarnings(warnings)
assert.equal(warningGroups.length, 3)
assert.deepEqual(groupWarnings([...warnings].reverse()), warningGroups)
assert.equal(warningGroups.reduce((sum, group) => sum + group.occurrences, 0), warnings.length)
assert.deepEqual(warningContext(warnings[0]), { column: 'payload' })
assert.deepEqual(warningContext({ context_json: 'malformed' }), { 'Unparsed context': 'malformed' })

const data: CaseData = {
  case: { case_id: 'gaps-test', case_name: 'Gaps test', examiner: 'test', workspace_path: '', created_at: '' },
  tables: { warnings, evidence_files: [{ evidence_id: 'e1', filename: 'visits.ibd' }], tool_runs: [{ tool_run_id: 't1' }] },
  analysis: {}, findings: input, finding_rules: catalogue, run: null,
}
const originalSnapshot = React.useSyncExternalStore
React.useSyncExternalStore = (subscribe, getSnapshot) => originalSnapshot(subscribe, getSnapshot, getSnapshot)
try {
  useApp.setState({ data, tablePages: {} })
  const html = renderToStaticMarkup(<GapsScreen />)
  for (const text of ['Warning groups', 'Notice groups', 'Extraction warning groups', 'Distinct subjects', 'Known title', 'visits.ibd', 'R-UNKNOWN']) assert.ok(html.includes(text), text)
  assert.equal((html.match(/View findings/g) ?? []).length, expected.length)
  assert.equal((html.match(/View warnings/g) ?? []).length, warningGroups.length)
  useApp.setState({ data: { ...data, findings: [], tables: { warnings: [] } } })
  assert.match(renderToStaticMarkup(<GapsScreen />), /No warning or notice findings available/)
  assert.match(renderToStaticMarkup(<GapsScreen />), /No extraction warnings available/)
} finally { React.useSyncExternalStore = originalSnapshot }

// Validate a stored clinic case read-only; no analysis rerun or fixture changes.
const clinic = resolve('../datasets/attack_lab/.validation-cases/03_clinic_interrupted_coverup')
if (existsSync(clinic)) {
  const python = process.env.FACTUMDB_PYTHON ?? (process.platform === 'win32' ? 'py' : 'python3')
  const script = [
    'import json, sqlite3, sys', 'from pathlib import Path',
    'from sidecar.views import _findings',
    'paths = sorted(Path(sys.argv[1]).glob("cases/*/case.db"), key=lambda p: p.stat().st_mtime, reverse=True)',
    'if not paths: print("null"); sys.exit(0)',
    'connection = sqlite3.connect(paths[0].as_uri() + "?mode=ro", uri=True)',
    'found = {}',
    'for (raw,) in connection.execute("SELECT j.value FROM analysis_results a, json_each(a.result_json, \'$.findings\') j WHERE json_extract(j.value, \'$.severity\') != \'info\'"):',
    '    _findings(json.loads(raw), found)',
    'print(json.dumps(list(found.values())))', 'connection.close()',
  ].join('\n')
  const result = spawnSync(python, [...(python === 'py' ? ['-3.11'] : []), '-B', '-c', script, clinic], { cwd: resolve('../backend'), encoding: 'utf8', windowsHide: true, maxBuffer: 128 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr || result.error?.message)
  const clinicFindings = JSON.parse(result.stdout) as Row[] | null
  if (clinicFindings) {
    const groups = groupFindings(clinicFindings)
    assert.equal(groups.reduce((sum, group) => sum + group.occurrences, 0), clinicFindings.length)
    for (const rule of ['R-RECON-002', 'R-ROLL-003']) {
      const grouped = groups.filter(group => group.rule === rule)
      assert.equal(grouped.length, 1)
      assert.equal(grouped[0].occurrences, clinicFindings.filter(f => f.rule_id === rule).length)
      assert.ok(grouped[0].occurrences > 100)
    }
    assert.deepEqual(groupFindings([...clinicFindings].reverse()), groups)
    console.log(`PASS: clinic case groups ${clinicFindings.length.toLocaleString()} findings into ${groups.length} rule/severity groups without losing occurrences.`)
  }
}
console.log('PASS: deterministic finding/warning grouping, preservation, catalogue fallback, and Gaps overview rendering.')
