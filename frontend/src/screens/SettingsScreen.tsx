import { useEffect, useState, type ReactNode } from 'react'
import { useApp } from '../store'
import { defaultPreferences, openWorkspace, pickBackupPath, request, type BackupPreview,
  type ExaminerProfile, type Preferences, type Settings, type StorageUsage, type ToolSettings } from '../lib/backend'
import { formatTime, timezoneLabel } from '../lib/timeDisplay'
import { navigationButton } from '../components/buttonStyles'
import { StatusMessage } from '../components/StatusMessage'

const field = 'mt-1 w-full rounded border border-line bg-page px-3 py-2 text-sm text-ink'
const section = 'space-y-4 rounded-md border border-line bg-panel p-5'
function Save({ children }: { children: ReactNode }) {
  const busy = useApp(s => s.busy)
  return <button type="submit" disabled={busy} className={navigationButton}>{children}</button>
}
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="accent-accent" />{label}</label>
}

function ProfileForm({ profile }: { profile: ExaminerProfile }) {
  const [draft, setDraft] = useState({ display_name: profile.display_name ?? '', organization: profile.organization ?? '', examiner_id: profile.examiner_id ?? '' })
  const username = useApp(s => s.user?.username)
  return <form className={section} onSubmit={e => { e.preventDefault(); void useApp.getState().settingsCommand('configure_profile', draft, 'Examiner profile saved.') }}>
    <h2 className="font-semibold">Examiner profile</h2>
    <p className="text-sm text-muted">Account: {username}. Profile details appear in future exports; recorded case and evidence identities are preserved.</p>
    {([['display_name', 'Display name'], ['organization', 'Organization'], ['examiner_id', 'Examiner ID']] as const).map(([key, label]) =>
      <label key={key} className="block text-sm">{label}<input className={field} maxLength={200} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} autoComplete={key === 'display_name' ? 'name' : key === 'organization' ? 'organization' : 'off'} /></label>)}
    <Save>Save profile</Save>
  </form>
}

function PasswordForm() {
  const [draft, setDraft] = useState({ current_password: '', new_password: '', password_confirmation: '' })
  return <form className={section} onSubmit={e => {
    e.preventDefault()
    void useApp.getState().settingsCommand<{ changed: boolean }>('change_password', draft, 'Password changed.').then(result => {
      if (result?.changed) setDraft({ current_password: '', new_password: '', password_confirmation: '' })
    })
  }}>
    <h2 className="font-semibold">Change password</h2><p className="text-sm text-muted">Use at least 12 characters for your new password.</p>
    {([['current_password', 'Current password'], ['new_password', 'New password'], ['password_confirmation', 'Confirm new password']] as const).map(([key, label]) =>
      <label key={key} className="block text-sm">{label}<input className={field} type="password" required minLength={key === 'current_password' ? 1 : 12} maxLength={1024}
        autoComplete={key === 'current_password' ? 'current-password' : 'new-password'} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
    {draft.password_confirmation && draft.new_password !== draft.password_confirmation && <p role="alert" className="text-sm text-red-700">New passwords do not match.</p>}<Save>Change password</Save>
  </form>
}

function PreferencesForm({ preferences }: { preferences: Preferences }) {
  const [draft, setDraft] = useState(preferences)
  const [preview] = useState(() => new Date().toISOString())
  const change = <K extends keyof Preferences>(key: K, value: Preferences[K]) => setDraft(current => ({ ...current, [key]: value }))
  return <form className={section} onSubmit={e => { e.preventDefault(); void useApp.getState().settingsCommand('configure_preferences', { ...draft }, 'Preferences saved.') }}>
    <h2 className="font-semibold">Session & time display</h2>
    <label className="block text-sm">Automatically lock after inactivity<select className={field} value={draft.lock_minutes} onChange={e => change('lock_minutes', Number(e.target.value))}>
      {[0, 1, 5, 15, 30, 60].map(minutes => <option key={minutes} value={minutes}>{minutes === 0 ? 'Never' : `${minutes} minute${minutes === 1 ? '' : 's'}`}</option>)}
    </select></label>
    <label className="block text-sm">Timestamp display<select className={field} value={draft.time_mode} onChange={e => change('time_mode', e.target.value as Preferences['time_mode'])}>
      <option value="utc">UTC</option><option value="local">Local system timezone</option><option value="custom">Custom UTC offset</option>
    </select></label>
    {draft.time_mode === 'custom' && <label className="block text-sm">UTC offset (minutes, −720 to +840)<input className={field} type="number" min={-720} max={840} step={1} required value={draft.utc_offset_minutes} onChange={e => change('utc_offset_minutes', Number(e.target.value))} />
      <span className="mt-1 block text-xs text-muted">For example, +330 means UTC+05:30. This fixed offset does not adjust for daylight saving.</span></label>}
    <p className="text-sm text-muted">{timezoneLabel(draft)}<br />Preview: {formatTime(preview, draft)}<br />Original evidence timestamps remain unchanged.</p>
    <Save>Save preferences</Save>
  </form>
}

function bytes(value: number) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = value > 0 ? Math.min(4, Math.floor(Math.log(value) / Math.log(1024))) : 0
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value / (1024 ** index)) + ' ' + units[index]
}

const storageCategories = [
  { key: 'databases_and_settings', label: 'Databases & settings', color: '#15696f' },
  { key: 'working', label: 'Evidence copies', color: '#63bdb5' },
  { key: 'raw-output', label: 'Raw outputs', color: '#8293bc' },
  { key: 'reports', label: 'Reports', color: '#bf9657' },
  { key: 'logs', label: 'Logs', color: '#97a59f' },
]

function StorageUsageSummary({ usage, cases }: { usage: StorageUsage; cases: { id: string; name: string }[] }) {
  const categories = storageCategories.map(category => ({ ...category, size: usage.categories[category.key] ?? 0 }))
  const breakdownTotal = categories.reduce((total, category) => total + category.size, 0)
  const caseUsage = Object.entries(usage.cases).sort((a, b) => b[1] - a[1])
  const percent = (size: number) => {
    const share = breakdownTotal > 0 ? size / breakdownTotal * 100 : 0
    return share > 0 && share < 0.1 ? '<0.1%' : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(share)}%`
  }
  return <div className="space-y-4" aria-label="Storage usage summary">
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-lg border border-line bg-thead p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Workspace storage</p>
        <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-ink">{bytes(usage.total_bytes)}</p>
        <p className="mt-1 text-xs text-muted">Across {caseUsage.length} {caseUsage.length === 1 ? 'case' : 'cases'}</p>
      </div>
      <div className="rounded-lg border border-line bg-thead p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Available on drive</p>
        <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-ink">{bytes(usage.free_bytes)}</p>
        <p className="mt-1 text-xs text-muted">Free space for evidence and backups</p>
      </div>
    </div>
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs"><h3 className="font-semibold text-ink">Workspace breakdown</h3><span className="text-muted">Share of workspace storage</span></div>
      <div role="img" aria-label={categories.map(category => `${category.label}: ${bytes(category.size)}, ${percent(category.size)}`).join('; ')} className="flex h-3 overflow-hidden rounded-full bg-page">
        {categories.filter(category => category.size > 0).map(category => <div key={category.key} title={`${category.label}: ${bytes(category.size)}`} style={{ width: `${category.size / breakdownTotal * 100}%`, backgroundColor: category.color }} />)}
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {categories.map(category => <div key={category.key} className="flex flex-col rounded-lg border border-line-soft bg-thead px-3 py-3">
          <dt className="flex min-h-8 items-start gap-2 text-xs text-muted"><span aria-hidden="true" className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: category.color }} />{category.label}</dt>
          <dd className="mt-2 text-lg font-semibold tabular-nums text-ink">{bytes(category.size)}</dd>
          <dd className="mt-0.5 text-[11px] tabular-nums text-muted">{percent(category.size)} of workspace</dd>
        </div>)}
      </dl>
    </div>
    <details className="rounded-lg border border-line-soft bg-thead">
      <summary className="cursor-pointer px-4 py-3 text-xs font-medium text-accent">Usage by case <span className="ml-1 text-muted">({caseUsage.length})</span></summary>
      {caseUsage.length > 0 ? <ul className="space-y-4 border-t border-line-soft p-4">{caseUsage.map(([id, size]) => <li key={id}>
        <div className="flex items-start justify-between gap-3 text-xs"><span className="min-w-0 break-words font-medium">{cases.find(item => item.id === id)?.name ?? id}</span><span className="shrink-0 tabular-nums text-muted">{bytes(size)}</span></div>
        <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-line-soft"><div className="h-full rounded-full bg-accent-light" style={{ width: `${usage.total_bytes > 0 ? Math.min(100, size / usage.total_bytes * 100) : 0}%` }} /></div>
      </li>)}</ul> : <p className="border-t border-line-soft px-4 py-3 text-xs text-muted">No case storage yet.</p>}
    </details>
  </div>
}

function StorageSettings({ workspace }: { workspace: string }) {
  const [usage, setUsage] = useState<StorageUsage>()
  const [backupPath, setBackupPath] = useState('')
  const [preview, setPreview] = useState<BackupPreview>()
  const [password, setPassword] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const busy = useApp(s => s.busy)
  const cases = useApp(s => s.cases)
  useEffect(() => {
    let active = true
    void request<StorageUsage>('storage_usage').then(result => {
      if (active) setUsage(result)
    }).catch(error => {
      if (active) useApp.getState().setError(error)
    })
    return () => { active = false }
  }, [workspace])
  const refreshUsage = async () => {
    const result = await useApp.getState().settingsCommand<StorageUsage>('storage_usage')
    if (result) setUsage(result)
  }
  const backup = async () => {
    setSelecting(true)
    try {
      const path = await pickBackupPath(false)
      if (!path) return
      const result = await useApp.getState().settingsCommand<{ path: string }>('backup_workspace', { path })
      if (result) useApp.setState({ notice: `Backup verified and saved to ${result.path}` })
    } catch (error) { useApp.getState().setError(error) }
    finally { setSelecting(false) }
  }
  const selectRestore = async () => {
    setPreview(undefined); setBackupPath(''); setPassword(''); setConfirmed(false); setSelecting(true)
    try {
      const path = await pickBackupPath(true)
      if (!path) return
      const result = await useApp.getState().settingsCommand<BackupPreview>('inspect_workspace_backup', { path })
      if (result) { setBackupPath(path); setPreview(result) }
    } catch (error) { useApp.getState().setError(error) }
    finally { setSelecting(false) }
  }
  return <section className={section} aria-labelledby="storage-heading">
    <h2 id="storage-heading" className="font-semibold">Storage & backup</h2><p className="break-all text-sm">{workspace}</p>
    <div className="flex flex-wrap gap-3"><button type="button" disabled={busy} className={navigationButton} onClick={() => { void openWorkspace().catch(error => useApp.getState().setError(error)) }}>Open workspace folder</button>
      <button type="button" disabled={busy} className={navigationButton} onClick={() => { void refreshUsage() }}>Refresh usage</button></div>
    {usage && <StorageUsageSummary usage={usage} cases={cases} />}
    {!usage && <p role="status" className="text-sm text-muted">Loading storage usage…</p>}
    <p className="text-sm text-muted">Full backups include cases, working copies, outputs, settings and local account records. External original evidence files are excluded. Backup archives are not encrypted.</p>
    <div className="flex flex-wrap gap-3"><button type="button" disabled={busy || selecting} className={navigationButton} onClick={() => { void backup() }}>Create workspace backup</button>
      <button type="button" disabled={busy || selecting} className={navigationButton} onClick={() => { void selectRestore() }}>Select backup to restore</button></div>
    {(busy || selecting) && <p role="status" className="text-sm text-muted">Working… Large backups can take several minutes.</p>}
    {preview && <form className="space-y-3 rounded border border-line bg-page p-4" onSubmit={e => {
      e.preventDefault()
      if (!confirmed) return
      void useApp.getState().settingsCommand('restore_workspace', { path: backupPath, sha256: preview.sha256, current_password: password })
    }}>
      <h3 className="font-semibold">Restore preview</h3><p className="break-all text-sm">{backupPath}</p>
      <p className="text-sm">Created: {preview.created_at} · {preview.case_count} cases · {bytes(preview.total_bytes)}</p>
      <p className="text-sm text-muted">Restore replaces this workspace and its accounts. The current workspace will be retained in a separate rollback folder. You will be signed out and must use credentials from the backup. Backups from another OS identity require account migration.</p>
      <label className="block text-sm">Current account password<input required type="password" maxLength={1024} autoComplete="current-password" className={field} value={password} onChange={e => setPassword(e.target.value)} /></label>
      <Check label="Replace the workspace with this backup" checked={confirmed} onChange={setConfirmed} />
      <button type="submit" disabled={busy || !confirmed || !password} className={navigationButton}>Restore workspace</button>
    </form>}
  </section>
}

function ToolForm({ settings }: { settings: Settings }) {
  const [draft, setDraft] = useState(settings.tools)
  const busy = useApp(s => s.busy)
  useEffect(() => { setDraft(settings.tools) }, [settings.tools])
  const names: [keyof Omit<ToolSettings, 'include_deleted'>, string][] = [
    ['innochecksum_path', 'innochecksum executable'], ['ibd2sdi_path', 'ibd2sdi executable'],
    ['ibd2sql_path', 'ibd2sql Python script'], ['mysqlbinlog_path', 'mysqlbinlog executable'], ['python_path', 'Python executable for ibd2sql'],
  ]
  return <form className={section} onSubmit={e => { e.preventDefault(); void useApp.getState().configure(draft) }}>
    <h2 className="font-semibold">Tools & runtime</h2><p className="text-sm text-muted">Tool versions and hashes are recorded when a tool runs. Paths are saved for this workspace.</p>
    {names.map(([key, label]) => <label key={key} className="block text-sm">{label}<input className={field} required={key !== 'ibd2sql_path'} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
    <Check label="Include deleted physical rows" checked={draft.include_deleted} onChange={include_deleted => setDraft({ ...draft, include_deleted })} />
    <div className="flex flex-wrap gap-3"><Save>Save tool settings</Save>{settings.bundled_tools && Object.keys(settings.bundled_tools).length > 0 &&
      <button type="button" disabled={busy} className={navigationButton} onClick={() => { void useApp.getState().configure({ ...draft, ...settings.bundled_tools }) }}>Use bundled tools</button>}</div>
  </form>
}

export function SettingsScreen() {
  const settings = useApp(s => s.settings)
  const username = useApp(s => s.user?.username)
  if (!settings) return <StatusMessage>Connect to the desktop backend to load settings.</StatusMessage>
  return <div key={username} className="max-w-5xl space-y-5">
    <div className="grid items-stretch gap-5 lg:grid-cols-2"><ProfileForm profile={settings.profile ?? {}} /><PasswordForm /></div>
    <PreferencesForm preferences={settings.preferences ?? defaultPreferences} /><StorageSettings workspace={settings.workspace} /><ToolForm settings={settings} />
  </div>
}
