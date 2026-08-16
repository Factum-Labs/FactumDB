/**
 * Presentation-layer grouping and layout for the reconciliation correlation graph.
 *
 * Everything here is a pure function over data that RecordCorrelationService and
 * ReconciliationService already produce. Nothing fetches, infers or fabricates:
 * an edge appears in a graph only if it appears in `correlationEdges`, and a
 * field value appears only if it appears in `reconRows`.
 */
import type {
  CorrelationEdge,
  EventType,
  ReconResult,
  ReconRow,
  RecordRef,
  Transaction,
} from '../data/types'

// ── Severity ─────────────────────────────────────────────────────────────────

/** A record is "flagged" if any of its fields classified as one of these. */
export const FLAG_RESULTS: ReconResult[] = ['Conflicting', 'Unresolved']

/** Higher wins. Conflicting outranks Unresolved, per the spec. */
const SEVERITY: Record<ReconResult, number> = {
  Conflicting: 5,
  Unresolved: 4,
  Partial: 3,
  Strong: 2,
  Exact: 1,
  Unsupported: 0,
}

export const isFlagResult = (r: ReconResult) => r === 'Conflicting' || r === 'Unresolved'

// ── Node kinds ───────────────────────────────────────────────────────────────

export type RecordNodeKind =
  | 'conflicting' // flagged, most-severe = Conflicting
  | 'unresolved' // flagged, most-severe = Unresolved
  | 'agreeing' // not flagged, but has reconciliation results (Exact / Strong / Partial)
  | 'context' // not flagged and never compared — included only because a group transaction touched it

export interface GroupRecord {
  record: RecordRef
  /** True when at least one field is Conflicting or Unresolved. */
  flagged: boolean
  /** Most severe result across this record's own fields, or null if never compared. */
  severity: ReconResult | null
  kind: RecordNodeKind
  /** Fields that caused the flag, e.g. [{ field: 'balance', result: 'Conflicting' }]. */
  triggers: { field: string; result: ReconResult }[]
  /** Every field result for this record, in service emission order. */
  fields: { field: string; result: ReconResult }[]
}

export interface FlaggedGroup {
  /** Stable id derived from canonical membership — same case data, same id. */
  id: string
  /** Transactions linking to any flagged record in this group, in commit order. */
  transactions: Transaction[]
  /** Flagged records plus context neighbours, ordered by table then primary key. */
  records: GroupRecord[]
  /** Edges confined to this group's transactions and records. */
  edges: CorrelationEdge[]
  /** Index into `reconRows` of the row that owns this group's toggle. */
  anchorRowIndex: number
}

// ── Canonical ordering ───────────────────────────────────────────────────────

/**
 * Compare two strings deterministically. Deliberately avoids localeCompare,
 * whose result depends on the host's ICU data — the layout must be byte-identical
 * across machines and runs.
 */
function cmpStr(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/** Numeric when both sides are integers, lexical otherwise. Never locale-dependent. */
function cmpKey(a: string, b: string): number {
  const na = Number(a)
  const nb = Number(b)
  if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return na < nb ? -1 : 1
  return cmpStr(a, b)
}

/** Canonical transaction order: binlog file, then position within that file. */
export function cmpTransaction(a: Transaction, b: Transaction): number {
  return cmpStr(a.binlogFile, b.binlogFile) || a.binlogPos - b.binlogPos || cmpStr(a.id, b.id)
}

/** Canonical record order: table name, then primary key. */
export function cmpRecord(a: RecordRef, b: RecordRef): number {
  return cmpStr(a.table, b.table) || cmpKey(a.pk, b.pk) || cmpStr(a.id, b.id)
}

// ── Grouping ─────────────────────────────────────────────────────────────────

function classify(fields: { field: string; result: ReconResult }[]): {
  flagged: boolean
  severity: ReconResult | null
  kind: RecordNodeKind
  triggers: { field: string; result: ReconResult }[]
} {
  if (fields.length === 0) {
    return { flagged: false, severity: null, kind: 'context', triggers: [] }
  }
  let severity = fields[0].result
  for (const f of fields) {
    if (SEVERITY[f.result] > SEVERITY[severity]) severity = f.result
  }
  const triggers = fields.filter((f) => isFlagResult(f.result))
  const flagged = triggers.length > 0
  const kind: RecordNodeKind = flagged
    ? severity === 'Conflicting'
      ? 'conflicting'
      : 'unresolved'
    : 'agreeing'
  return { flagged, severity, kind, triggers }
}

/**
 * Cluster flagged records into groups by connected components: two flagged
 * records share a group when at least one transaction links to both.
 *
 * Call this once per case (memoize it) — never per row render.
 */
export function buildFlaggedGroups(
  records: RecordRef[],
  transactions: Transaction[],
  edges: CorrelationEdge[],
  reconRows: ReconRow[],
): FlaggedGroup[] {
  const recordById = new Map(records.map((r) => [r.id, r]))
  const txById = new Map(transactions.map((t) => [t.id, t]))

  // Per-record field results, in service emission order.
  const fieldsByRecord = new Map<string, { field: string; result: ReconResult }[]>()
  reconRows.forEach((row) => {
    const list = fieldsByRecord.get(row.recordId) ?? []
    list.push({ field: row.field, result: row.result })
    fieldsByRecord.set(row.recordId, list)
  })

  const info = new Map<string, GroupRecord>()
  for (const record of records) {
    const fields = fieldsByRecord.get(record.id) ?? []
    info.set(record.id, { record, fields, ...classify(fields) })
  }

  const flaggedIds = records.filter((r) => info.get(r.id)!.flagged).map((r) => r.id)
  if (flaggedIds.length === 0) return []
  const flaggedSet = new Set(flaggedIds)

  // Union-find over flagged records.
  const parent = new Map<string, string>(flaggedIds.map((id) => [id, id]))
  const find = (x: string): string => {
    let root = x
    while (parent.get(root) !== root) root = parent.get(root)!
    while (parent.get(x) !== root) {
      const next = parent.get(x)!
      parent.set(x, root)
      x = next
    }
    return root
  }
  const union = (a: string, b: string) => {
    const ra = find(a)
    const rb = find(b)
    if (ra !== rb) parent.set(ra, rb)
  }

  const recordsByTx = new Map<string, string[]>()
  for (const e of edges) {
    if (!txById.has(e.txId) || !recordById.has(e.recordId)) continue
    const list = recordsByTx.get(e.txId) ?? []
    if (!list.includes(e.recordId)) list.push(e.recordId)
    recordsByTx.set(e.txId, list)
  }
  for (const touched of recordsByTx.values()) {
    const flaggedTouched = touched.filter((id) => flaggedSet.has(id))
    for (let i = 1; i < flaggedTouched.length; i++) union(flaggedTouched[0], flaggedTouched[i])
  }

  // Collect components.
  const componentMembers = new Map<string, string[]>()
  for (const id of flaggedIds) {
    const root = find(id)
    const list = componentMembers.get(root) ?? []
    list.push(id)
    componentMembers.set(root, list)
  }

  const groups: FlaggedGroup[] = []
  for (const members of componentMembers.values()) {
    const memberSet = new Set(members)

    // Left column: every transaction linking to any flagged member.
    const groupTxIds = new Set<string>()
    for (const [txId, touched] of recordsByTx) {
      if (touched.some((id) => memberSet.has(id))) groupTxIds.add(txId)
    }

    // Right column: flagged members plus any other record those transactions
    // touched — this is what surfaces the hub pattern. No further hops.
    const groupRecordIds = new Set<string>(members)
    for (const txId of groupTxIds) {
      for (const id of recordsByTx.get(txId)!) groupRecordIds.add(id)
    }

    const groupTransactions = [...groupTxIds].map((id) => txById.get(id)!).sort(cmpTransaction)
    const groupRecords = [...groupRecordIds]
      .map((id) => info.get(id)!)
      .sort((a, b) => cmpRecord(a.record, b.record))

    const groupEdges = edges
      .filter((e) => groupTxIds.has(e.txId) && groupRecordIds.has(e.recordId))
      .sort(
        (a, b) =>
          cmpTransaction(txById.get(a.txId)!, txById.get(b.txId)!) ||
          cmpRecord(recordById.get(a.recordId)!, recordById.get(b.recordId)!),
      )

    // The toggle lives on the first flagged field of the first record in
    // canonical order — resolved back to that row's index in the table.
    const firstFlagged = groupRecords.find((r) => r.flagged)!
    const anchorRowIndex = reconRows.findIndex(
      (row) => row.recordId === firstFlagged.record.id && isFlagResult(row.result),
    )

    groups.push({
      id: groupRecords
        .filter((r) => r.flagged)
        .map((r) => r.record.id)
        .join('+'),
      transactions: groupTransactions,
      records: groupRecords,
      edges: groupEdges,
      anchorRowIndex,
    })
  }

  // Page order follows the table: group whose anchor row comes first, first.
  return groups.sort((a, b) => a.anchorRowIndex - b.anchorRowIndex || cmpStr(a.id, b.id))
}

/** Row-level decoration for the reconciliation table. */
export interface RowDecoration {
  /** Group whose toggle this row owns, if any. */
  anchorOf: FlaggedGroup | null
  /** Group that already covers this row's record, if the row is not the anchor. */
  coveredBy: FlaggedGroup | null
}

export function decorateRows(rows: ReconRow[], groups: FlaggedGroup[]): RowDecoration[] {
  const groupByFlaggedRecord = new Map<string, FlaggedGroup>()
  for (const g of groups) {
    for (const r of g.records) if (r.flagged) groupByFlaggedRecord.set(r.record.id, g)
  }
  const anchorByIndex = new Map<number, FlaggedGroup>()
  for (const g of groups) anchorByIndex.set(g.anchorRowIndex, g)

  return rows.map((row, i) => {
    const anchorOf = anchorByIndex.get(i) ?? null
    if (anchorOf) return { anchorOf, coveredBy: null }
    return { anchorOf: null, coveredBy: groupByFlaggedRecord.get(row.recordId) ?? null }
  })
}

// ── Deterministic layout ─────────────────────────────────────────────────────
//
// Node positions are computed directly from the canonical sort order above.
// No force simulation, no physics, no randomness, no measurement of rendered
// text: the same group object always yields the same numbers, so repeated runs
// over the same evidence produce pixel-identical layouts.

export const LAYOUT = {
  PAD: 18,
  TX_W: 184,
  TX_H: 46,
  REC_W: 240,
  REC_H: 58,
  ROW_GAP: 14,
  COL_GAP: 214,
} as const

export interface PositionedNode {
  x: number
  y: number
  w: number
  h: number
  cx: number
  cy: number
}

export interface PositionedEdge {
  txId: string
  recordId: string
  eventType: EventType
  path: string
  labelX: number
  labelY: number
}

export interface GraphLayout {
  width: number
  height: number
  txNodes: Map<string, PositionedNode>
  recNodes: Map<string, PositionedNode>
  edges: PositionedEdge[]
}

export function computeGraphLayout(group: FlaggedGroup): GraphLayout {
  const { PAD, TX_W, TX_H, REC_W, REC_H, ROW_GAP, COL_GAP } = LAYOUT

  const nTx = group.transactions.length
  const nRec = group.records.length
  const txColH = nTx * TX_H + Math.max(0, nTx - 1) * ROW_GAP
  const recColH = nRec * REC_H + Math.max(0, nRec - 1) * ROW_GAP
  const contentH = Math.max(txColH, recColH)

  const width = PAD + TX_W + COL_GAP + REC_W + PAD
  const height = contentH + PAD * 2

  const txX = PAD
  const recX = PAD + TX_W + COL_GAP
  const txTop = PAD + Math.round((contentH - txColH) / 2)
  const recTop = PAD + Math.round((contentH - recColH) / 2)

  const txNodes = new Map<string, PositionedNode>()
  group.transactions.forEach((t, i) => {
    const y = txTop + i * (TX_H + ROW_GAP)
    txNodes.set(t.id, { x: txX, y, w: TX_W, h: TX_H, cx: txX + TX_W / 2, cy: y + TX_H / 2 })
  })

  const recNodes = new Map<string, PositionedNode>()
  group.records.forEach((r, j) => {
    const y = recTop + j * (REC_H + ROW_GAP)
    recNodes.set(r.record.id, { x: recX, y, w: REC_W, h: REC_H, cx: recX + REC_W / 2, cy: y + REC_H / 2 })
  })

  const bend = Math.round(COL_GAP * 0.45)

  // Labels sit at a point along each curve rather than all at the midpoint,
  // otherwise edges leaving the same transaction stack their labels on top of
  // one another. Each transaction's outgoing edges are spread evenly across the
  // column gap at t = (i+1)/(n+1). Both i and n come from the canonical edge
  // ordering, not from render order, so the placement stays deterministic.
  const edgeCountPerTx = new Map<string, number>()
  for (const e of group.edges) {
    edgeCountPerTx.set(e.txId, (edgeCountPerTx.get(e.txId) ?? 0) + 1)
  }
  const seenPerTx = new Map<string, number>()

  const edges: PositionedEdge[] = group.edges.map((e) => {
    const from = txNodes.get(e.txId)!
    const to = recNodes.get(e.recordId)!
    const x1 = from.x + from.w
    const y1 = from.cy
    const x2 = to.x
    const y2 = to.cy
    const cx1 = x1 + bend
    const cx2 = x2 - bend

    const nth = seenPerTx.get(e.txId) ?? 0
    seenPerTx.set(e.txId, nth + 1)
    const t = (nth + 1) / (edgeCountPerTx.get(e.txId)! + 1)

    return {
      txId: e.txId,
      recordId: e.recordId,
      eventType: e.eventType,
      path: `M ${x1} ${y1} C ${cx1} ${y1}, ${cx2} ${y2}, ${x2} ${y2}`,
      labelX: Math.round(cubic(t, x1, cx1, cx2, x2)),
      labelY: Math.round(cubic(t, y1, y1, y2, y2)) - 5,
    }
  })

  return { width, height, txNodes, recNodes, edges }
}

/** Cubic Bézier evaluated at t. Pure arithmetic — no sampling, no randomness. */
function cubic(t: number, p0: number, p1: number, p2: number, p3: number): number {
  const u = 1 - t
  return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3
}
