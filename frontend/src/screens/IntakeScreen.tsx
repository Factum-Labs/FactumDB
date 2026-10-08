import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import { Badge } from '../components/Badge'
import { display, pickEvidence, request, type CaseData, type Row } from '../lib/backend'
import { useApp } from '../store'

const input = 'h-[29px] w-full rounded border border-line-input bg-panel px-[9px] text-[12px] text-ink focus:border-accent-light'
const button = 'h-[26px] rounded border border-line-input bg-panel px-2.5 text-[11.5px] text-ink hover:bg-page disabled:cursor-not-allowed disabled:opacity-40'
const primary = 'h-[26px] rounded bg-accent px-[11px] text-[11.5px] font-medium text-white hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-40'
const kindLabels: Record<string, string> = { ibd: 'InnoDB tablespace', binlog: 'Row binary log', binlog_index: 'Binary-log index' }

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex flex-col gap-1 text-[11px] text-muted">{label}{children}</label>
}

function Notes({ data }: { data: CaseData }) {
  const busy = useApp(s => s.busy)
  const [notes, setNotes] = useState(data.case.examiner_notes ?? '')
  const [saved, setSaved] = useState(data.case.examiner_notes ?? '')
  const [saving, setSaving] = useState(false)
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (saving || busy) return
    setSaving(true)
    try {
      const result = await request<CaseData>('save_case_notes', { case_id: data.case.case_id, notes })
      setSaved(notes)
      if (useApp.getState().data?.case.case_id === data.case.case_id) {
        useApp.setState(current => ({ data: current.data ? { ...current.data, case: result.case } : null }))
      }
    } catch (error) { useApp.getState().setError(error) }
    finally { setSaving(false) }
  }
  return <form onSubmit={event => { void save(event) }} className="space-y-2">
    <Field label="Examiner notes"><textarea rows={3} value={notes} onChange={event => setNotes(event.target.value)}
      className="w-full resize-y rounded border border-line-input bg-panel px-[9px] py-[7px] text-[12px] text-ink focus:border-accent-light" /></Field>
    <div className="flex items-center justify-between gap-2">
      <button type="submit" className={button} disabled={saving || busy || notes === saved}>{saving ? 'Saving…' : 'Save notes'}</button>
      <span role="status" className="text-[11px] text-muted">{notes === saved ? 'Saved' : 'Unsaved changes'}</span>
    </div>
  </form>
}

function fileSize(value: Row['size_bytes']): string {
  const bytes = Number(value)
  if (!Number.isFinite(bytes)) return display(value)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function IntakeScreen() {
  const data = useApp(s => s.data)
  const busy = useApp(s => s.busy)
  const [path, setPath] = useState('')
  const [selected, setSelected] = useState('')
  const [page, setPage] = useState(0)
  const [hovering, setHovering] = useState(false)
  const [working, setWorking] = useState(false)
  const dropZone = useRef<HTMLDivElement>(null)
  const operation = useRef(false)
  const caseId = data?.case.case_id
  const active = !!data?.run && !data.run.stopped
  const locked = busy || active || working
  useEffect(() => { setPath(''); setSelected(''); setPage(0) }, [caseId])
  useEffect(() => {
    if (!isTauri() || !caseId) return
    let disposed = false
    let unlisten: (() => void) | undefined
    void getCurrentWebview().onDragDropEvent(event => {
      if (disposed) return
      if (event.payload.type === 'leave') { setHovering(false); return }
      const state = useApp.getState()
      const bounds = dropZone.current?.getBoundingClientRect()
      const position = event.payload.position
      const scale = window.devicePixelRatio || 1
      const inside = !!bounds && position.x / scale >= bounds.left && position.x / scale <= bounds.right &&
        position.y / scale >= bounds.top && position.y / scale <= bounds.bottom
      const allowed = inside && !operation.current && !state.busy && state.data?.case.case_id === caseId && (!state.data.run || state.data.run.stopped)
      setHovering(allowed && event.payload.type !== 'drop')
      if (allowed && event.payload.type === 'drop') void state.registerEvidence(event.payload.paths)
    }).then(stop => { if (disposed) stop(); else unlisten = stop })
      .catch(error => { if (!disposed) useApp.getState().setError(error) })
    return () => { disposed = true; unlisten?.() }
  }, [caseId])
  if (!data) return <div className="rounded-md border border-line bg-panel p-4 text-sm text-muted">Open or create a case to register evidence.</div>
  const evidence = data.tables.evidence_files ?? []
  const verified = evidence.filter(e => e.verification_status === 'verified').length
  const detail = evidence.find(e => e.evidence_id === selected)
  const pages = Math.max(1, Math.ceil(evidence.length / 100))
  const current = Math.min(page, pages - 1)
  const register = async (event: FormEvent) => {
    event.preventDefault()
    if (!locked && await useApp.getState().registerEvidence([path])) setPath('')
  }
  const browse = async () => {
    if (locked) return
    try {
      const paths = await pickEvidence()
      if (paths.length && useApp.getState().data?.case.case_id === caseId) await useApp.getState().registerEvidence(paths)
    } catch (error) { useApp.getState().setError(error) }
  }
  const verifyAll = async () => {
    if (locked || operation.current) return
    operation.current = true
    setWorking(true)
    try {
      for (const file of evidence.filter(e => e.verification_status !== 'verified')) {
        if (useApp.getState().data?.case.case_id !== caseId) break
        await useApp.getState().verifyEvidence(String(file.evidence_id))
        if (useApp.getState().error) break
      }
    } finally { operation.current = false; setWorking(false) }
  }
  return <div className="grid max-w-[1180px] items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
    <section aria-labelledby="case-details-heading" className="min-w-0 rounded-md border border-line bg-panel p-3.5">
      <h2 id="case-details-heading" className="mb-3 text-[12px] font-semibold">Case details</h2>
      <div className="flex flex-col gap-[11px]">
        <Field label="Case ID"><input readOnly value={data.case.case_id} className={input + ' font-mono'} /></Field>
        <Field label="Case name"><input readOnly value={data.case.case_name} className={input} /></Field>
        <Field label="Examiner"><input readOnly value={data.case.examiner} className={input} /></Field>
        <Field label="Case workspace"><input readOnly value={data.case.workspace_path} title={data.case.workspace_path} className={input + ' font-mono text-[11.5px]'} /></Field>
        <Notes key={data.case.case_id} data={data} />
      </div>
    </section>
    <div className="min-w-0 space-y-3">
      <div ref={dropZone} className={'flex min-h-[76px] flex-wrap items-center justify-center gap-2.5 rounded-md border border-dashed px-3 py-4 text-[12px] text-muted ' +
        (hovering ? 'border-accent bg-accent-soft' : 'border-line-input bg-panel')}>
        <span>Drop <span className="font-mono">.ibd</span> files and binary logs here, or</span>
        <button type="button" className={button} disabled={locked} onClick={() => { void browse() }}>Browse…</button>
      </div>
      <section aria-labelledby="registered-evidence-heading" className="overflow-hidden rounded-md border border-line bg-panel">
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-3 py-[9px]">
          <h2 id="registered-evidence-heading" className="text-[12px] font-semibold">Registered evidence</h2>
          <span className="mr-auto text-[11px] text-muted">{evidence.length} files · {verified} verified · originals untouched</span>
          <button type="button" className={primary} disabled={locked || !evidence.length || verified === evidence.length} onClick={() => { void verifyAll() }}>{working ? 'Verifying…' : 'Register & verify'}</button>
        </div>
        <div className="overflow-auto">
          <table className="w-full min-w-[600px] table-fixed text-left">
            <colgroup><col className="w-[25%]" /><col className="w-[17%]" /><col className="w-[12%]" /><col className="w-[28%]" /><col className="w-[18%]" /></colgroup>
            <thead className="border-b border-line bg-thead text-[10.5px] uppercase tracking-[.07em] text-dim"><tr>
              {['File', 'Type', 'Size', 'SHA-256', 'Working copy'].map(label => <th key={label} className="px-3 py-[7px] font-semibold">{label}</th>)}
            </tr></thead>
            <tbody>{evidence.slice(current * 100, (current + 1) * 100).map(file => {
              const hash = display(file.source_sha256)
              const status = String(file.verification_status)
              return <tr key={String(file.evidence_id)} className={'border-b border-line-soft text-[12px] ' + (file.evidence_id === selected ? 'bg-accent-soft' : '')}>
                <td className="break-all px-3 py-2 font-mono"><button type="button" className="text-left hover:text-accent hover:underline" onClick={() => setSelected(String(file.evidence_id))}>{display(file.filename)}</button></td>
                <td className="px-3 py-2 text-muted">{kindLabels[String(file.kind)] ?? display(file.kind)}</td>
                <td className="px-3 py-2 text-muted">{fileSize(file.size_bytes)}</td>
                <td className="truncate px-3 py-2 font-mono text-[11.5px] text-muted" title={hash}>{hash.length > 20 ? `${hash.slice(0, 12)}…${hash.slice(-4)}` : hash}</td>
                <td className="px-3 py-2"><Badge tone={status === 'verified' ? 'ok' : status === 'hash_mismatch' ? 'bad' : 'neutral'}>{status === 'verified' ? 'Verified' : status === 'hash_mismatch' ? 'Mismatch' : 'Registered'}</Badge></td>
              </tr>
            })}</tbody>
          </table>
        </div>
        {!evidence.length && <p className="px-3 py-4 text-[12px] text-muted">Browse or drop files to register evidence.</p>}
        {pages > 1 && <div className="flex items-center gap-3 px-3 py-2 text-[11px] text-muted">
          <button type="button" className={button} disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
          <span>Page {current + 1} of {pages} · {evidence.length} files</span>
          <button type="button" className={button} disabled={current + 1 === pages} onClick={() => setPage(current + 1)}>Next</button>
        </div>}
      </section>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <details className="min-w-0 flex-1 rounded-md border border-line bg-panel px-3 py-2 text-[11px] text-muted">
          <summary className="cursor-pointer">Register by file path</summary>
          <form onSubmit={event => { void register(event) }} className="mt-3 flex items-end gap-2">
            <label className="min-w-0 flex-1">Evidence file path<input required disabled={locked} className={input + ' mt-1'} value={path} onChange={event => setPath(event.target.value)} placeholder="Absolute path to an evidence file" /></label>
            <button type="submit" className={button} disabled={locked || !path.trim()}>Register file</button>
          </form>
        </details>
        <button type="button" className={button} disabled={busy || working || !evidence.length} onClick={() => useApp.getState().go('pipeline')}>Open pipeline</button>
      </div>
      {active && <p className="rounded-md border border-line bg-panel px-3 py-2 text-[11px] text-muted">Finish or cancel the active pipeline before registering additional evidence.</p>}
      {detail && <details open className="rounded-md border border-line bg-panel p-3 text-[11px]">
        <summary className="cursor-pointer font-medium">Evidence paths and hashes</summary>
        <p className="mt-2 text-muted">Registered by: {detail.actor_username == null ? 'Not recorded (older evidence)' : display(detail.actor_username)}{detail.actor_id != null ? ` · Actor ID: ${display(detail.actor_id)}` : ''}</p>
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono">{JSON.stringify(detail, null, 2)}</pre>
        <button type="button" className={button + ' mt-3'} disabled={locked || detail.verification_status === 'verified'} onClick={() => { void useApp.getState().verifyEvidence(String(detail.evidence_id)) }}>Verify working copy</button>
      </details>}
    </div>
  </div>
}
