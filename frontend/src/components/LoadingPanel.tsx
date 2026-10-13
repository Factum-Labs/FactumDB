export function LoadingPanel({ error, retry, label = 'Loading results' }: { error?: string; retry?: () => void; label?: string }) {
  return <section className="min-h-[240px] rounded-md border border-line bg-panel p-4" aria-busy={!error} aria-label={label}>
    {error ? <p role="alert" className="text-xs text-danger">{error} <button className="ml-3 underline" onClick={retry}>Retry</button></p>
      : <div role="status"><span className="sr-only">{label}</span>{[0, 1, 2, 3, 4, 5].map(i => <div key={i} className="mb-4 h-4 animate-pulse rounded bg-thead" style={{ width: `${85 - (i % 3) * 15}%` }} />)}</div>}
  </section>
}

export function QueryError({ error, retry }: { error: string; retry: () => void }) {
  return error ? <p role="alert" className="text-xs text-danger">{error} <button className="ml-3 underline" onClick={retry}>Retry</button></p> : null
}
