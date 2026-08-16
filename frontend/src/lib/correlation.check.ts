/**
 * Acceptance-criteria harness for the correlation grouping and layout.
 * Run with: npm run check:graph
 */
import { correlationEdges, reconRows, records, transactions } from '../data/caseData'
import { buildFlaggedGroups, computeGraphLayout, decorateRows } from './correlation'

let failures = 0
function check(name: string, cond: boolean, detail = '') {
  if (cond) {
    console.log(`  PASS  ${name}`)
  } else {
    failures++
    console.log(`  FAIL  ${name}${detail ? ` — ${detail}` : ''}`)
  }
}

const build = () => buildFlaggedGroups(records, transactions, correlationEdges, reconRows)

console.log('\nGroups built from case FDB-2026-014:\n')
const groups = build()
for (const g of groups) {
  console.log(`  group ${g.id}`)
  console.log(`    anchor row      ${g.anchorRowIndex} (${reconRows[g.anchorRowIndex].recordId} · ${reconRows[g.anchorRowIndex].field})`)
  console.log(`    transactions    ${g.transactions.map((t) => `${t.id}(${t.binlogFile}:${t.binlogPos})`).join(', ')}`)
  console.log(`    records         ${g.records.map((r) => `${r.record.id}[${r.kind}]`).join(', ')}`)
  console.log(`    edges           ${g.edges.map((e) => `${e.txId}-${e.eventType}->${e.recordId}`).join(', ')}`)
}

console.log('\nAcceptance criteria:\n')

// 1. Repeatability — identical group membership, node ordering and layout.
const a = JSON.stringify(build(), replacer)
const b = JSON.stringify(build(), replacer)
check('same case data produces identical groups and ordering', a === b)

const layoutA = build().map((g) => serializeLayout(g))
const layoutB = build().map((g) => serializeLayout(g))
check('same case data produces identical layout geometry', JSON.stringify(layoutA) === JSON.stringify(layoutB))

// 2. One transaction touching two flagged records → exactly one graph.
const tx1452Group = groups.filter((g) =>
  g.transactions.some((t) => t.id === 'TX-1452') &&
  g.records.some((r) => r.record.id === 'accounts:101' && r.flagged) &&
  g.records.some((r) => r.record.id === 'accounts:205' && r.flagged),
)
check(
  'TX-1452 touching flagged 101 and 205 yields exactly one graph covering both',
  tx1452Group.length === 1,
  `got ${tx1452Group.length}`,
)

// 3. Every group has at least one Conflicting/Unresolved member.
check(
  'no group exists without a Conflicting/Unresolved member',
  groups.every((g) => g.records.some((r) => r.flagged)),
)

// 4. Zero flagged rows → zero graph UI.
const allExact = reconRows.map((r) => ({ ...r, result: 'Exact' as const }))
check(
  'zero Conflicting/Unresolved rows produces zero groups',
  buildFlaggedGroups(records, transactions, correlationEdges, allExact).length === 0,
)

// 5. No fabricated edges — every rendered edge exists in correlationEdges.
const known = new Set(correlationEdges.map((e) => `${e.txId}|${e.recordId}|${e.eventType}`))
check(
  'every rendered edge comes from RecordCorrelationService output',
  groups.every((g) => g.edges.every((e) => known.has(`${e.txId}|${e.recordId}|${e.eventType}`))),
)

// 6. Exactly one toggle per group; no record covered by two graphs.
const decorations = decorateRows(reconRows, groups)
const anchors = decorations.filter((d) => d.anchorOf)
check('one toggle rendered per group', anchors.length === groups.length, `${anchors.length} toggles for ${groups.length} groups`)

const coveredTwice = new Map<string, Set<string>>()
for (const g of groups) {
  for (const r of g.records) {
    if (!r.flagged) continue
    const s = coveredTwice.get(r.record.id) ?? new Set()
    s.add(g.id)
    coveredTwice.set(r.record.id, s)
  }
}
check(
  'no flagged record appears in more than one graph',
  [...coveredTwice.values()].every((s) => s.size === 1),
)

// 7. Anchor is the first flagged field of the first record in canonical order.
check(
  'anchors sit on a Conflicting/Unresolved row',
  groups.every((g) => ['Conflicting', 'Unresolved'].includes(reconRows[g.anchorRowIndex].result)),
)

// 8. Transactions in commit order, records in table+PK order.
check(
  'transactions sorted by binlog file then position',
  groups.every((g) =>
    g.transactions.every((t, i) => {
      if (i === 0) return true
      const p = g.transactions[i - 1]
      return p.binlogFile < t.binlogFile || (p.binlogFile === t.binlogFile && p.binlogPos <= t.binlogPos)
    }),
  ),
)
check(
  'records sorted by table then primary key',
  groups.every((g) =>
    g.records.every((r, i) => {
      if (i === 0) return true
      const p = g.records[i - 1].record
      return (
        p.table < r.record.table ||
        (p.table === r.record.table && Number(p.pk) <= Number(r.record.pk))
      )
    }),
  ),
)

console.log(`\n${failures === 0 ? 'All checks passed.' : `${failures} check(s) failed.`}\n`)
if (failures > 0) throw new Error(`${failures} correlation check(s) failed`)

function replacer(_k: string, v: unknown) {
  return v instanceof Map ? [...v.entries()] : v
}

function serializeLayout(g: Parameters<typeof computeGraphLayout>[0]) {
  const l = computeGraphLayout(g)
  return {
    width: l.width,
    height: l.height,
    tx: [...l.txNodes.entries()],
    rec: [...l.recNodes.entries()],
    edges: l.edges,
  }
}
