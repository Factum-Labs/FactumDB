// Design tokens lifted verbatim from the Claude Design handoff (FactumDB.dc.html).
// Keep these in sync with tailwind.config.js — SVG/inline consumers read them from here.

export const A = 'oklch(0.52 0.14 255)' // accent (blue)
export const GRN = 'oklch(0.55 0.11 150)'
export const AMB = 'oklch(0.62 0.13 75)' // amber — transaction "Incomplete"
export const ORG = 'oklch(0.62 0.15 55)' // orange — reconciliation "Unresolved"
export const RED = 'oklch(0.55 0.16 25)' // red — reconciliation "Conflicting"
export const GRY = '#9a998f'

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'neutral' | 'info' | 'unresolved'

type Tone = { color: string; bg: string; border: string }

/**
 * Badge palette. `ok` / `warn` / `bad` / `neutral` / `info` are the tones already
 * established in the design handoff.
 *
 * `unresolved` is new: the spec requires Conflicting and Unresolved to be
 * separable at a glance because they are different failure modes (evidence
 * disagrees vs. evidence is insufficient). `bad` stays at hue 25 (red) for
 * Conflicting; `unresolved` sits at hue 55 (orange), far enough from `warn`
 * at hue 75-85 that it does not collide with the transaction "Incomplete" badge.
 */
export const TONES: Record<BadgeTone, Tone> = {
  ok: { color: 'oklch(0.42 0.09 150)', bg: 'oklch(0.96 0.03 150)', border: 'oklch(0.88 0.05 150)' },
  warn: { color: 'oklch(0.45 0.09 70)', bg: 'oklch(0.97 0.03 85)', border: 'oklch(0.89 0.06 85)' },
  bad: { color: 'oklch(0.45 0.13 25)', bg: 'oklch(0.96 0.03 25)', border: 'oklch(0.89 0.06 25)' },
  neutral: { color: '#5c5b55', bg: '#f2f1ee', border: '#e2e1dd' },
  info: { color: 'oklch(0.42 0.11 255)', bg: 'oklch(0.96 0.03 255)', border: 'oklch(0.88 0.05 255)' },
  unresolved: { color: 'oklch(0.45 0.12 50)', bg: 'oklch(0.96 0.035 60)', border: 'oklch(0.88 0.07 55)' },
}

export const dot = (c: string): React.CSSProperties => ({
  width: 7,
  height: 7,
  borderRadius: '50%',
  flex: 'none',
  background: c,
})
