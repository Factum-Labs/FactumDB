import { useState } from 'react'
import { useScreenQuery } from '../lib/useScreenQuery'
import type { Json } from '../lib/backend'
import type { Screen } from '../data/types'
import { LoadingPanel } from './LoadingPanel'

export function CoverageDetails({ kind, screen, title }: { kind: string; screen: Screen; title: string }) {
  const [open, setOpen] = useState(false)
  const query = useScreenQuery<{ coverage: Json }>('get_screen_coverage', { kind }, screen, open)
  return <details className="rounded-md border border-line bg-panel p-4" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-xs font-medium">{title}</summary>
    {open && (query.value ? <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify(query.value.coverage, null, 2)}</pre> : <LoadingPanel error={query.error} retry={query.retry} label="Loading coverage" />)}
  </details>
}
