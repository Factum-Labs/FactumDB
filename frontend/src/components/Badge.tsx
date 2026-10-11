import { TONES, type BadgeTone } from '../lib/tokens'

export function Badge({ tone, children }: { tone: BadgeTone; children: React.ReactNode }) {
  const t = TONES[tone]
  return (
    <span
      className="inline-flex h-[18px] items-center rounded-[3px] px-[7px] text-[10.5px] font-semibold tracking-[.03em]"
      style={{ color: t.color, background: t.bg, border: `1px solid ${t.border}` }}
    >
      {children}
    </span>
  )
}
