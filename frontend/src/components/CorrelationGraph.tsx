import { useMemo } from 'react'
import type { EventType, TxStatus } from '../data/types'
import { AMB, GRN, GRY, ORG, RED } from '../lib/tokens'
import {
  computeGraphLayout,
  LAYOUT,
  type FlaggedGroup,
  type GroupRecord,
  type RecordNodeKind,
} from '../lib/correlation'
import { useApp } from '../store'

/**
 * Bipartite transaction→record correlation graph for one flagged group.
 *
 * Standalone and reusable: it takes a pre-computed group and renders it. The
 * case-wide bipartite view can reuse this with a different group-selection
 * strategy and no changes here.
 *
 * Layout is computed by `computeGraphLayout` — a pure function of the group's
 * canonical ordering. There is no force simulation, no physics and no
 * randomness anywhere in this file, so repeated renders over the same case data
 * are pixel-identical.
 */
export function CorrelationGraph({
  group,
  onSelectTransaction,
  onSelectRecord,
}: {
  group: FlaggedGroup
  onSelectTransaction?: (txId: string) => void
  onSelectRecord?: (recordId: string) => void
}) {
  const openTransaction = useApp((s) => s.openTransaction)
  const openRecord = useApp((s) => s.openRecord)
  const goTx = onSelectTransaction ?? openTransaction
  const goRec = onSelectRecord ?? openRecord

  const layout = useMemo(() => computeGraphLayout(group), [group])

  const flaggedCount = group.records.filter((r) => r.flagged).length
  const contextCount = group.records.length - flaggedCount

  return (
    <div className="rounded-md border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
        <div className="text-[12px] font-semibold">Correlation graph</div>
        <div className="text-[11px] text-muted">
          {group.transactions.length} transaction{group.transactions.length === 1 ? '' : 's'} ·{' '}
          {flaggedCount} flagged record{flaggedCount === 1 ? '' : 's'}
          {contextCount > 0 ? ` · ${contextCount} shown for context` : ''}
        </div>
        <div className="flex-1" />
        <Legend />
      </div>

      <div className="overflow-auto p-1">
        <svg
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="img"
          aria-label={`Correlation graph linking ${group.transactions.length} transactions to ${group.records.length} records`}
          style={{ display: 'block' }}
        >
          <defs>
            <marker
              id="fdb-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 7 4 L 0 7 z" fill="#9aa8a5" />
            </marker>
          </defs>

          <text
            x={LAYOUT.PAD}
            y={12}
            className="fill-dim"
            style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.07em' }}
          >
            TRANSACTIONS
          </text>
          <text
            x={LAYOUT.PAD + LAYOUT.TX_W + LAYOUT.COL_GAP}
            y={12}
            className="fill-dim"
            style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.07em' }}
          >
            RECORDS
          </text>

          {/* Edges first so nodes paint over the endpoints. */}
          {layout.edges.map((e) => (
            <g key={`${e.txId}->${e.recordId}`}>
              <path
                d={e.path}
                fill="none"
                stroke="#b3c2bf"
                strokeWidth={1.4}
                strokeDasharray={dashFor(e.eventType)}
                markerEnd="url(#fdb-arrow)"
              />
              <rect
                x={e.labelX - labelWidth(e.eventType) / 2}
                y={e.labelY - 9}
                width={labelWidth(e.eventType)}
                height={13}
                rx={2}
                fill="#ffffff"
                stroke="#dde5e3"
              />
              <text
                x={e.labelX}
                y={e.labelY}
                textAnchor="middle"
                className="fill-dim"
                style={{ fontSize: 8.5, fontWeight: 600, letterSpacing: '.05em' }}
              >
                {e.eventType}
              </text>
            </g>
          ))}

          {group.transactions.map((t) => {
            const n = layout.txNodes.get(t.id)!
            const c = TX_COLOR[t.status]
            return (
              <g
                key={t.id}
                className="cursor-pointer"
                onClick={() => goTx(t.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') goTx(t.id)
                }}
              >
                <title>{`${t.id} · ${t.status} · ${t.binlogFile} pos ${t.binlogPos}`}</title>
                <rect
                  x={n.x}
                  y={n.y}
                  width={n.w}
                  height={n.h}
                  rx={5}
                  fill="#ffffff"
                  stroke={c.border}
                  strokeWidth={1}
                />
                <rect x={n.x} y={n.y} width={3.5} height={n.h} rx={1.5} fill={c.bar} />
                <circle cx={n.x + 16} cy={n.y + 17} r={3.5} fill={c.bar} />
                <text
                  x={n.x + 26}
                  y={n.y + 20}
                  style={{ fontSize: 12, fontWeight: 500, fontFamily: "'IBM Plex Mono', monospace" }}
                  fill="#282828"
                >
                  {t.id}
                </text>
                <text x={n.x + 26} y={n.y + 34} style={{ fontSize: 10.5 }} fill={c.text}>
                  {t.status}
                </text>
                <text
                  x={n.x + n.w - 10}
                  y={n.y + 34}
                  textAnchor="end"
                  style={{ fontSize: 9.5, fontFamily: "'IBM Plex Mono', monospace" }}
                  fill="#858585"
                >
                  {`${t.binlogFile.replace('binlog.', '')} · ${t.binlogPos}`}
                </text>
              </g>
            )
          })}

          {group.records.map((r) => {
            const n = layout.recNodes.get(r.record.id)!
            const c = REC_COLOR[r.kind]
            return (
              <g
                key={r.record.id}
                className="cursor-pointer"
                onClick={() => goRec(r.record.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') goRec(r.record.id)
                }}
              >
                <title>{`${r.record.label} — ${subtitleFor(r)}`}</title>
                <rect
                  x={n.x}
                  y={n.y}
                  width={n.w}
                  height={n.h}
                  rx={5}
                  fill={c.bg}
                  stroke={c.border}
                  strokeWidth={r.flagged ? 1.3 : 1}
                />
                <rect x={n.x + n.w - 3.5} y={n.y} width={3.5} height={n.h} rx={1.5} fill={c.bar} />
                <text
                  x={n.x + 11}
                  y={n.y + 20}
                  style={{
                    fontSize: 11.5,
                    fontWeight: r.flagged ? 500 : 400,
                    fontFamily: "'IBM Plex Mono', monospace",
                  }}
                  fill={c.title}
                >
                  {r.record.label}
                </text>
                <text
                  x={n.x + 11}
                  y={n.y + 36}
                  style={{ fontSize: 10.5, fontFamily: "'IBM Plex Mono', monospace" }}
                  fill={c.sub}
                >
                  {truncate(subtitleFor(r), 30)}
                </text>
                <text x={n.x + 11} y={n.y + 49} style={{ fontSize: 9.5 }} fill={c.key}>
                  {truncate(r.record.key, 34)}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}

// ── Presentation helpers ─────────────────────────────────────────────────────

// Transaction nodes stay on a plain white ground; status is carried by the bar,
// the dot and the status label only.
const TX_COLOR: Record<TxStatus, { bar: string; border: string; text: string }> = {
  Committed: { bar: GRN, border: '#bfded4', text: '#256e5c' },
  'Rolled back': { bar: GRY, border: '#d5dedb', text: '#5c5c5c' },
  Incomplete: { bar: AMB, border: 'oklch(0.89 0.06 85)', text: 'oklch(0.45 0.09 70)' },
}

const REC_COLOR: Record<
  RecordNodeKind,
  { bg: string; border: string; bar: string; title: string; sub: string; key: string }
> = {
  conflicting: {
    bg: 'oklch(0.97 0.02 25)',
    border: 'oklch(0.86 0.07 25)',
    bar: RED,
    title: '#282828',
    sub: 'oklch(0.45 0.13 25)',
    key: '#a1837f',
  },
  unresolved: {
    bg: 'oklch(0.97 0.025 60)',
    border: 'oklch(0.86 0.08 55)',
    bar: ORG,
    title: '#282828',
    sub: 'oklch(0.45 0.12 50)',
    key: '#9c8763',
  },
  // An agreeing record is a compared record like any other flagged one, so it
  // carries a tint and an ink title; only `context` is deliberately muted.
  agreeing: {
    bg: '#e9f4f1',
    border: '#bfded4',
    bar: '#4fae99',
    title: '#282828',
    sub: '#2f7a68',
    key: '#7d938d',
  },
  context: {
    bg: '#f4f7f6',
    border: '#d5dedb',
    bar: '#c3d0cd',
    title: '#6e6e6e',
    sub: '#8a8a8a',
    key: '#a0aeab',
  },
}

function subtitleFor(r: GroupRecord): string {
  if (r.triggers.length > 0) return r.triggers.map((t) => `${t.field}: ${t.result}`).join(', ')
  if (r.severity) return `${r.fields.length} field${r.fields.length === 1 ? '' : 's'}: ${r.severity}`
  return 'not compared'
}

const dashFor = (t: EventType) =>
  t === 'UPDATE' ? undefined : t === 'INSERT' ? '6 3' : '1.5 3'

const labelWidth = (t: EventType) => (t === 'UPDATE' ? 42 : t === 'INSERT' ? 38 : 38)

function truncate(s: string, max: number) {
  return s.length <= max ? s : `${s.slice(0, max - 1)}…`
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted">
      {/* Read off REC_COLOR so a retint of the nodes cannot leave the key behind. */}
      <LegendSwatch kind="conflicting" label="Conflicting" />
      <LegendSwatch kind="unresolved" label="Unresolved" />
      <LegendSwatch kind="agreeing" label="Agrees" />
      <LegendSwatch kind="context" label="Context" />
      <span className="h-3 w-px bg-line" />
      <LegendLine dash={undefined} label="UPDATE" />
      <LegendLine dash="4 2" label="INSERT" />
      <LegendLine dash="1 2" label="DELETE" />
    </div>
  )
}

function LegendSwatch({ kind, label }: { kind: RecordNodeKind; label: string }) {
  const c = REC_COLOR[kind]
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="h-2 w-2 rounded-[2px]"
        style={{ background: c.bar, border: `1px solid ${c.border}` }}
      />
      {label}
    </span>
  )
}

function LegendLine({ dash, label }: { dash?: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <svg width="14" height="6" aria-hidden="true">
        <line x1="0" y1="3" x2="14" y2="3" stroke="#9aa8a5" strokeWidth="1.4" strokeDasharray={dash} />
      </svg>
      {label}
    </span>
  )
}
