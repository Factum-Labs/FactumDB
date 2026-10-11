import { useState } from 'react'
import { useApp } from '../store'
import { navigationButton } from '../components/buttonStyles'

export function LockedScreen() {
  const user = useApp(s => s.user)
  const busy = useApp(s => s.busy)
  const [error, setError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  return <main className="flex min-h-screen items-center justify-center bg-page p-6 text-ink">
    <form className="w-full max-w-sm space-y-4 rounded-md border border-line bg-panel p-6" onSubmit={event => {
      event.preventDefault()
      setError(null)
      void useApp.getState().unlockSession(password).then(ok => {
        if (ok) setPassword('')
        else setError(useApp.getState().error ?? 'Could not unlock the session.')
      })
    }}>
      <h1 className="text-xl font-semibold">Session locked</h1>
      <p className="text-sm text-muted">Enter the password for {user?.username} to resume. An executing analysis stage can finish while the screen is locked.</p>
      <label className="block text-sm">Password<input autoFocus required type="password" autoComplete="current-password" maxLength={1024} value={password} onChange={e => setPassword(e.target.value)} className="mt-1 w-full rounded border border-line bg-page p-2" /></label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <div className="flex gap-3"><button disabled={busy} className={navigationButton}>Unlock</button>
        <button type="button" disabled={busy} className={navigationButton} onClick={() => { void useApp.getState().signOut() }}>Sign out</button></div>
      {busy && <p role="status" className="text-xs text-muted">Waiting for the current operation to finish…</p>}
    </form>
  </main>
}
