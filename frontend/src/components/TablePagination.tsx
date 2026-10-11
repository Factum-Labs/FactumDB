import { navigationButton } from './buttonStyles'

const button = navigationButton

export function TablePagination({ page, count, onPage, label = 'results', name = 'Table pagination' }: {
  page: number; count: number; onPage: (page: number) => void; label?: string; name?: string
}) {
  const pages = Math.max(1, Math.ceil(count / 100))
  const current = Math.min(page, pages - 1)
  if (pages <= 1) return null
  return <nav aria-label={name} className="flex flex-wrap items-center justify-center gap-3 border-t border-line bg-thead px-3 py-2.5 text-xs">
    <button type="button" disabled={current === 0} onClick={() => onPage(current - 1)} className={button}><span aria-hidden="true">‹</span>Previous</button>
    <span aria-live="polite" aria-atomic="true" className="flex h-[30px] items-center justify-center gap-3 px-3 text-center font-medium tabular-nums text-accent">
      <span>Page {(current + 1).toLocaleString()} of {pages.toLocaleString()}</span><span aria-hidden="true">|</span><span>{count.toLocaleString()} {label}</span>
    </span>
    <button type="button" disabled={current + 1 === pages} onClick={() => onPage(current + 1)} className={button}>Next<span aria-hidden="true">›</span></button>
  </nav>
}
