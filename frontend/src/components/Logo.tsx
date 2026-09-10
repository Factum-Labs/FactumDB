import { BRAND_SLATE, BRAND_TEAL, BRAND_TEAL_LIGHT } from '../lib/tokens'

/**
 * The FactumDB mark: a magnifying glass whose lens holds the "F". Drawn inline
 * rather than loaded as an image so it stays crisp at the small sizes the title
 * bar needs, and so it inherits the page's colour tokens.
 */
export function LogoMark({ size = 26 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 26 26"
      role="img"
      aria-label="FactumDB"
      className="flex-none"
    >
      <g stroke={BRAND_TEAL} fill="none" strokeLinecap="round">
        <line x1="17.3" y1="17.3" x2="23.8" y2="23.8" strokeWidth="2.5" />
        <circle cx="11" cy="11" r="8.5" strokeWidth="1.9" />
      </g>
      {/* The F fills most of the lens, as in the logo artwork — at title-bar
          sizes a much smaller F turns to mush inside the ring. */}
      <path fill={BRAND_SLATE} d="M7.1 5.9 H14.9 V8.1 H9.7 V10.3 H13.85 V12.5 H9.7 V16.1 H7.1 Z" />
    </svg>
  )
}

/**
 * Full lockup — the mark plus the "actumDB" wordmark, which reads as "FactumDB"
 * because the "F" sits inside the lens. The wordmark is live text in the app's
 * own typeface: a raster wordmark shrunk to title-bar height is unreadable.
 */
// The lens ends at 20.45 of the mark's 26-unit box; the rest is dead space held
// open for the handle. Pull the wordmark back into it so "actum" sits ~2 units
// off the glass, the way it does in the logo artwork, instead of ~6.
const WORDMARK_TUCK = (26 - 20.45 - 2) / 26

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <div className="flex items-center" title="FactumDB">
      <LogoMark size={size} />
      <span
        className="font-semibold leading-none tracking-[-.005em]"
        style={{ fontSize: size * 0.46, marginLeft: -size * WORDMARK_TUCK, color: BRAND_SLATE }}
      >
        <span style={{ color: BRAND_TEAL_LIGHT }}>actum</span>DB
      </span>
    </div>
  )
}
