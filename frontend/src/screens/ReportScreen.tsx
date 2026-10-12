import { useEffect, useRef, useState } from 'react'
import { useApp } from '../store'
import { defaultPreferences, display, pickExportPath, request, rows, type CaseData } from '../lib/backend'
import { navigationButton } from '../components/buttonStyles'
import { formatTime } from '../lib/timeDisplay'

type ReportProfile = 'investigator' | 'full'
interface ExportSection {
  id: string; title: string; optional: boolean; dependencies: string[]
  default_profiles: ReportProfile[]
}
interface Preview {
  preview_token: string; page: number; pages: number; lines: string[]
  format: string; redacted: boolean
  profile: ReportProfile; json_size_bytes: number
  selection: { sections: string[]; automatic_sections: string[]; partial: boolean }
  counts: Record<string, { included: number; summarized: number; excluded: number }>
}

export function ReportScreen() {
  const state = useApp()
  const history = rows(state.data?.tables?.reports)
  const caseId = state.data?.case.case_id
  const [path, setPath] = useState('')
  const [redacted, setRedacted] = useState(true)
  const [profile, setProfile] = useState<ReportProfile>('investigator')
  const [sections, setSections] = useState<ExportSection[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [working, setWorking] = useState(false)
  const generation = useRef(0)
  const selectionKey = selected.join(',')
  const requestKey = `${caseId}:${state.reportFormat}:${profile}:${redacted}:${selectionKey}`
  const currentKey = useRef(requestKey)
  currentKey.current = requestKey
  const [previewKey, setPreviewKey] = useState('')
  const ready = preview !== null && previewKey === requestKey

  useEffect(() => {
    let active = true
    request<ExportSection[]>('get_export_sections', {}).then(catalog => {
      if (!active) return
      setSections(catalog)
      setSelected(catalog.filter(section => section.default_profiles.includes('investigator')).map(section => section.id))
    }).catch(error => { if (active) useApp.getState().setError(error) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    generation.current++
    setPreview(null)
    setWorking(false)
  }, [caseId, state.reportFormat, profile, redacted, selectionKey])
  useEffect(() => { setPath('') }, [caseId, state.reportFormat])
  useEffect(() => () => { generation.current++ }, [])

  const makePreview = async () => {
    const ticket = ++generation.current
    setWorking(true)
    setPreview(null)
    try {
      const result = await request<Preview>('preview_export', {
        case_id: caseId, format: state.reportFormat, profile, redacted, sections: selected,
      })
      if (ticket === generation.current && currentKey.current === requestKey) {
        setPreview(result)
        setPreviewKey(requestKey)
      }
    } catch (error) { if (ticket === generation.current) state.setError(error) }
    finally { if (ticket === generation.current) setWorking(false) }
  }
  const turnPage = async (page: number) => {
    if (!ready || !preview) return
    const ticket = ++generation.current
    setWorking(true)
    try {
      const result = await request<Preview>('export_preview_page', {
        preview_token: preview.preview_token, page,
      })
      if (ticket === generation.current && currentKey.current === requestKey) setPreview(result)
    } catch (error) {
      if (ticket === generation.current) { setPreview(null); state.setError(error) }
    } finally { if (ticket === generation.current) setWorking(false) }
  }
  const choose = async () => {
    try {
      const chosen = await pickExportPath(state.reportFormat)
      if (chosen && currentKey.current === requestKey) setPath(state.reportFormat === 'CSV'
        ? `${chosen}/factumdb-${caseId}-${Date.now()}` : chosen)
    } catch (error) { state.setError(error) }
  }
  const save = async () => {
    if (!ready || !preview) return
    const ticket = ++generation.current
    setWorking(true)
    try {
      const result = await request<{ path: string }>('export_case', {
        case_id: caseId, format: state.reportFormat, profile, path, redacted, sections: selected,
        preview_token: preview.preview_token,
      })
      if (ticket !== generation.current || currentKey.current !== requestKey || useApp.getState().data?.case.case_id !== caseId) return
      setPreview(null)
      useApp.setState({ notice: `Export saved to ${result.path}` })
      const data = await request<CaseData>('get_case_data', { case_id: caseId })
      if (useApp.getState().data?.case.case_id === caseId) useApp.setState({ data })
    } catch (error) {
      if (ticket === generation.current) { setPreview(null); state.setError(error) }
    } finally { if (ticket === generation.current) setWorking(false) }
  }
  const disabled = working || state.busy || !state.pipelineComplete || sections.length === 0
  return <div className="grid items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
    <form className="space-y-5 rounded-md border border-line bg-panel p-5"
      onSubmit={event => { event.preventDefault(); void save() }}>
      <label className="block text-xs font-semibold">Report detail
        <select className="mt-2 w-full rounded border border-line-input bg-panel px-2 py-2 text-xs"
          disabled={disabled} value={profile} onChange={event => {
            const next = event.target.value as ReportProfile
            setProfile(next)
            setSelected(sections.filter(section => section.default_profiles.includes(next)).map(section => section.id))
          }}>
          <option value="investigator">Investigator report</option>
          <option value="full">Full evidence export</option>
        </select>
      </label>
      <p className="text-xs leading-relaxed text-muted">{profile === 'investigator'
        ? 'Includes every non-Exact comparison, warnings and limitations. Routine matches become counts. Add supporting data below.'
        : 'Includes every unique observation and analysis result, with repeated data stored once. Large evidence sets can still produce large exports.'}</p>
      <fieldset disabled={disabled} className="space-y-3">
        <legend className="mb-3 text-sm font-semibold">Format</legend>
        <div className="flex overflow-hidden rounded border border-line-input">
          {['PDF', 'JSON', 'CSV'].map(format => <button key={format} type="button"
            aria-pressed={state.reportFormat === format} onClick={() => state.setFormat(format)}
            className={`flex-1 border-r border-line-input py-2 text-xs last:border-r-0 ${state.reportFormat === format ? 'bg-ink font-semibold text-white' : 'bg-panel text-muted'}`}>
            {format}
          </button>)}
        </div>
      </fieldset>
      <label className="block text-xs font-semibold">Content
        <select className="mt-2 w-full rounded border border-line-input bg-panel px-2 py-2 text-xs"
          disabled={disabled} value={redacted ? 'redacted' : 'full'}
          onChange={event => setRedacted(event.target.value === 'redacted')}>
          <option value="redacted">Redacted sharing copy</option>
          <option value="full">Original values (sensitive)</option>
        </select>
      </label>
      <p className="text-xs leading-relaxed text-muted">{redacted
        ? 'Values and text identifiers become aliases. Personal metadata, paths, commands and diagnostic text are removed. Original case data stays intact.'
        : 'Includes original values and sensitive metadata in the selected sections.'}</p>
      <fieldset disabled={disabled} className="space-y-2.5">
        <legend className="mb-3 text-sm font-semibold">Sections</legend>
        <div className="mb-3 flex gap-3 text-xs">
          <button type="button" className="text-accent underline" onClick={() => setSelected(sections.map(section => section.id))}>Select all</button>
          <button type="button" className="text-accent underline" onClick={() => setSelected(sections.filter(section => section.default_profiles.includes(profile)).map(section => section.id))}>Reset defaults</button>
          <button type="button" className="text-accent underline" onClick={() => setSelected([])}>Clear all</button>
        </div>
        {sections.filter(section => !section.optional).map(({ id, title }) => <label key={id} className="flex items-start gap-2 text-xs">
          <input type="checkbox" className="mt-0.5 accent-accent" checked={selected.includes(id)}
            onChange={event => setSelected(current => event.target.checked
              ? sections.map(section => section.id).filter(key => key === id || current.includes(key))
              : current.filter(key => key !== id))} />
          {title}
        </label>)}
        <p className="pt-3 text-xs font-semibold">Optional supporting data</p>
        <p className="text-[11px] text-muted">These additions can substantially increase export size. Required evidence and provenance metadata are included automatically.</p>
        {sections.filter(section => section.optional).map(({ id, title }) => <label key={id} className="flex items-start gap-2 text-xs">
          <input type="checkbox" className="mt-0.5 accent-accent" checked={selected.includes(id)}
            onChange={event => setSelected(current => event.target.checked
              ? sections.map(section => section.id).filter(key => key === id || current.includes(key))
              : current.filter(key => key !== id))} />
          {title}
        </label>)}
      </fieldset>
      <button type="button" className={`${navigationButton} w-full justify-center`}
        disabled={disabled || selected.length === 0} onClick={() => { void makePreview() }}>
        {working ? 'Preparing…' : ready ? 'Refresh preview' : 'Preview export'}
      </button>
      {!state.pipelineComplete && <p className="text-xs text-muted">Complete the pipeline before previewing or exporting.</p>}
      <label className="block text-xs font-semibold">{state.reportFormat === 'CSV' ? 'New CSV folder path' : `New ${state.reportFormat} file path`}
        <input required className="mt-2 w-full rounded border border-line-input bg-page px-2 py-2 text-xs font-normal"
          disabled={disabled} value={path} onChange={event => setPath(event.target.value)} />
      </label>
      <button type="button" className={navigationButton} disabled={disabled}
        onClick={() => { void choose() }}>Choose destination</button>
      <button type="submit" className={`${navigationButton} w-full justify-center`}
        disabled={disabled || !ready || !path.trim()}>Generate {state.reportFormat} {state.reportFormat === 'PDF' ? 'report' : 'export'}</button>
      <p className="text-[11px] text-muted">Review a fresh preview before exporting. Existing exports are never overwritten.</p>
      <section aria-label="Export history" className="space-y-2 border-t border-line pt-4">
        <h2 className="text-xs font-semibold">Export history</h2>
        {history.length === 0 && <p className="text-xs text-muted">No recorded exports.</p>}
        {history.map(report => <p key={display(report.report_id)} className="break-words text-xs text-muted">
          {display(report.format).toUpperCase()} v{display(report.version)} · {formatTime(display(report.created_at), state.settings?.preferences ?? defaultPreferences)}
          <br />Exported by {report.actor_username ? display(report.actor_username) : 'Unknown (historical export)'}
        </p>)}
      </section>
    </form>
    <section aria-label="Export preview" aria-busy={working}
      className="min-h-[620px] min-w-0 rounded-md border border-line bg-panel p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <h2 className="text-sm font-semibold">Report preview</h2>
        {ready && preview && <nav aria-label="Preview pages" className="flex items-center gap-3 text-xs">
          <button type="button" className={navigationButton} disabled={disabled || preview.page === 1}
            onClick={() => { void turnPage(preview.page - 1) }}>Previous</button>
          <span>Page {preview.page} of {preview.pages}</span>
          <button type="button" className={navigationButton} disabled={disabled || preview.page === preview.pages}
            onClick={() => { void turnPage(preview.page + 1) }}>Next</button>
        </nav>}
      </div>
      {ready && preview ? <>
        <div className="mb-4 space-y-2 text-xs text-muted">
          <p>Prepared JSON: {(preview.json_size_bytes / (1024 * 1024)).toFixed(2)} MB
            {preview.selection?.partial && ' · Partial report'}</p>
          <p>Included sections: {preview.selection?.sections.map(id => sections.find(section => section.id === id)?.title ?? id).join(', ')}</p>
          {preview.selection?.automatic_sections.length > 0 && <p>Automatically included: {preview.selection.automatic_sections.map(id => sections.find(section => section.id === id)?.title ?? id).join(', ')}</p>}
          <details><summary className="cursor-pointer">Included, summarized and excluded counts</summary>
            <table className="mt-2 w-full text-left text-[11px]"><thead><tr><th>Data</th><th>Included</th><th>Summarized</th><th>Excluded</th></tr></thead>
              <tbody>{Object.entries(preview.counts ?? {}).map(([name, count]) => <tr key={name}>
                <td className="pr-3">{name.replaceAll('_', ' ')}</td><td>{count.included}</td><td>{count.summarized}</td><td>{count.excluded}</td>
              </tr>)}</tbody></table>
          </details>
        </div>
        <p className="mb-4 text-[11px] text-muted">{state.reportFormat === 'PDF'
          ? 'These text pages are used to generate the PDF with locally bundled fonts. Unsupported characters appear as Unicode escapes.'
          : 'Readable preview of the selected content. JSON and CSV preserve their structured formats.'}
          {redacted && ' Pseudonymization does not guarantee anonymity. This copy is unsuitable for independent reanalysis.'}</p>
        <pre className="overflow-x-auto whitespace-pre font-mono text-[11px] leading-5 text-ink"
          data-testid="export-preview-content">{preview.lines.join('\n')}</pre>
      </> : <div className="py-24 text-center text-sm text-muted" role="status">
        {working ? 'Preparing the selected report…' : 'Choose sections and select Preview export to review the report.'}
      </div>}
    </section>
  </div>
}
