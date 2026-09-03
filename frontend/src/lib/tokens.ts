// Design tokens for the light / teal theme.
// Keep these in sync with tailwind.config.js — SVG/inline consumers read them from here.
//
// Palette anchors:
//   #EEF2F0  page ground        #858585  dim text
//   #63BDB5  teal light         #15696F  teal dark (accent)
//   #282828  ink

export const A = '#15696f' // accent (teal)
export const A_DARK = '#0f4f54'
export const A_LIGHT = '#63bdb5'
export const A_SOFT = '#e2efee' // tinted fill for accent-toned surfaces
export const GRN = '#2f8a72'
export const AMB = 'oklch(0.62 0.13 75)' // amber — transaction "Incomplete"
export const ORG = 'oklch(0.62 0.15 55)' // orange — reconciliation "Unresolved"
export const RED = 'oklch(0.55 0.16 25)' // red — reconciliation "Conflicting"
export const GRY = '#858585'

// Neutral surfaces / rules, cool-grey to sit under the teal accent.
export const PAGE = '#eef2f0'
export const PANEL = '#ffffff'
export const CHROME = '#e4ebe9'
export const THEAD = '#f4f7f6'
export const LINE = '#d5dedb'
export const LINE_SOFT = '#e8eeec'
export const LINE_MID = '#dde5e3'
export const INK = '#282828'
export const MUTED = '#6e6e6e'
export const DIM = '#858585'
export const HOVER = '#eaf0ee' // row / button hover wash

// Brand palette, sampled from the FactumDB logo artwork. The mark's lens and
// handle are BRAND_TEAL; the "F" and the "DB" of the wordmark are BRAND_SLATE;
// "actum" is the lighter BRAND_TEAL_LIGHT. See src-tauri/icons/source/icon.svg,
// which uses BRAND_TEAL over a dark ground for the application icon.
export const BRAND_TEAL = '#15696f'
export const BRAND_TEAL_LIGHT = '#63bdb5'
export const BRAND_SLATE = '#282828'

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'neutral' | 'info' | 'unresolved'

type Tone = { color: string; bg: string; border: string }

/**
 * Badge palette. `ok` / `warn` / `bad` / `neutral` / `info` are the tones already
 * established in the design handoff, retuned for the teal light theme: `info`
 * now reads as the accent teal rather than blue, and `ok` sits at a green that
 * stays distinguishable from that teal.
 *
 * `unresolved` is separate from `bad` because they are different failure modes
 * (evidence disagrees vs. evidence is insufficient). `bad` stays at hue 25 (red)
 * for Conflicting; `unresolved` sits at hue 55 (orange), far enough from `warn`
 * at hue 75-85 that it does not collide with the transaction "Incomplete" badge.
 */
export const TONES: Record<BadgeTone, Tone> = {
  ok: { color: '#256e5c', bg: '#e8f4f0', border: '#bfded4' },
  warn: { color: 'oklch(0.45 0.09 70)', bg: 'oklch(0.97 0.03 85)', border: 'oklch(0.89 0.06 85)' },
  bad: { color: 'oklch(0.45 0.13 25)', bg: 'oklch(0.96 0.03 25)', border: 'oklch(0.89 0.06 25)' },
  neutral: { color: '#5c5c5c', bg: '#eef2f0', border: '#d5dedb' },
  info: { color: '#15696f', bg: '#e2efee', border: '#b4d9d5' },
  unresolved: { color: 'oklch(0.45 0.12 50)', bg: 'oklch(0.96 0.035 60)', border: 'oklch(0.88 0.07 55)' },
}

export const dot = (c: string): React.CSSProperties => ({
  width: 7,
  height: 7,
  borderRadius: '50%',
  flex: 'none',
  background: c,
})
