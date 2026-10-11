import type { ReactNode } from 'react'

export function StatusMessage({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div role={error ? 'alert' : 'status'} className="rounded-md border border-line bg-panel p-4 text-xs text-muted">
    {children}
  </div>
}
