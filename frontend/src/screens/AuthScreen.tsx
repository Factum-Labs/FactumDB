import { useState, type FormEvent } from 'react'
import { Logo } from '../components/Logo'
import { useApp } from '../store'

export function AuthScreen() {
  const [signup, setSignup] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const busy = useApp(s => s.busy)
  const checked = useApp(s => s.authChecked)
  const error = useApp(s => s.error)
  const authenticate = useApp(s => s.authenticate)
  const initialize = useApp(s => s.initialize)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try { await authenticate(username, password, signup ? confirmation : undefined) }
    finally { setPassword(''); setConfirmation('') }
  }
  const input = 'rounded border border-line bg-page px-3 py-2 text-sm'
  return <main className="flex min-h-screen items-center justify-center bg-page p-6 text-ink">
    <section className="w-full max-w-md rounded-md border border-line bg-panel p-7">
      <Logo size={44} />
      <h1 className="mt-5 text-xl font-semibold">{signup ? 'Create examiner account' : 'Sign in to FactumDB'}</h1>
      <p className="mt-2 text-sm text-muted">Use your local account to access cases and examine evidence.</p>
      {error && <p role="alert" className="mt-4 whitespace-pre-wrap rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {!checked ? <div className="mt-5 text-sm" role="status">
        {busy ? 'Connecting to the desktop backend…' : <button onClick={() => { void initialize() }} className="text-accent underline">Retry connection</button>}
      </div> : <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
        <fieldset disabled={busy} className="flex flex-col gap-4 disabled:opacity-60">
          <label className="flex flex-col gap-1 text-sm">Username
            <input className={input} value={username} onChange={e => setUsername(e.target.value)} autoComplete="username"
              autoCapitalize="none" spellCheck={false} pattern="[A-Za-z0-9_.\-]{3,64}" minLength={3} maxLength={64} required aria-describedby="username-help" />
          </label>
          <p id="username-help" className="-mt-2 text-xs text-muted">3–64 letters, numbers, dots, underscores or hyphens.</p>
          <label className="flex flex-col gap-1 text-sm">Password
            <input className={input} type="password" value={password} onChange={e => setPassword(e.target.value)}
              autoComplete={signup ? 'new-password' : 'current-password'} minLength={signup ? 12 : undefined} maxLength={1024} required />
          </label>
          {signup && <>
            <label className="flex flex-col gap-1 text-sm">Confirm password
              <input className={input} type="password" value={confirmation} onChange={e => setConfirmation(e.target.value)}
                autoComplete="new-password" minLength={12} maxLength={1024} required />
            </label>
            <p className="text-xs text-muted">Use at least 12 characters. Verify using your device’s security to finish sign-up. Your operating system handles the verification method and prompt.</p>
          </>}
          <button type="submit" className="rounded bg-accent px-3 py-2 text-sm font-medium text-white"
            disabled={busy || (signup && password !== confirmation)}>{busy ? signup ? 'Complete device verification…' : 'Signing in…' : signup ? 'Verify device and sign up' : 'Sign in'}</button>
          <button type="button" className="text-sm text-accent underline" onClick={() => {
            setSignup(s => !s); setPassword(''); setConfirmation(''); useApp.setState({ error: null })
          }}>{signup ? 'Already have an account? Sign in' : 'Create an account'}</button>
        </fieldset>
      </form>}
    </section>
  </main>
}
