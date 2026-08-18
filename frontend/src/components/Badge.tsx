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

export function Dot({ color, size = 7 }: { color: string; size?: number }) {
  return (
    <span
      className="flex-none rounded-full"
      style={{ width: size, height: size, background: color }}
    />
  )
}

export function Card({
  children,
  className = '',
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-md border border-line bg-panel ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-[.07em] text-dim">{children}</div>
  )
}
