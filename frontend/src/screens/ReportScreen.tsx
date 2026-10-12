import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useApp } from '../store'
import { defaultPreferences, display, pickExportPath, request, rows, type CaseData } from '../lib/backend'
import { navigationButton } from '../components/buttonStyles'
import { formatTime } from '../lib/timeDisplay'

const PdfPreview = lazy(() => import('../components/PdfPreview').then(module => ({ default: module.PdfPreview })))
interface ExportDefinition { format: 'JSON' | 'PDF'; title: string; description: string }
interface Preview {
  preview_token: string; page: number; pages: number; format: 'JSON' | 'PDF'; redacted: boolean
  detail: 'full' | 'summary'; size_bytes: number
  counts: Record<string, number | { included: number; summarized: number; excluded: number }>
  classification_totals?: Record<string, Record<string, number>>
  manifest: { case_id: string; exported_at: string; engine_revision: number; analysis_format_version: number }
}

interface Preparation { preparation_token: string; stage: string; processed: number }

export function ReportScreen() {
  const state = useApp()
  const history = rows(state.data?.tables?.reports)
  const caseId = state.data?.case.case_id
  const [path, setPath] = useState('')
  const [redacted, setRedacted] = useState(true)
  const [definitions, setDefinitions] = useState<ExportDefinition[]>([])
  const [zoom, setZoom] = useState(1)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [working, setWorking] = useState(false)
  const [progress, setProgress] = useState('')
  const preparation = useRef('')
  const generation = useRef(0)
  const requestKey = `${caseId}:${state.reportFormat}:${redacted}`
  const currentKey = useRef(requestKey)
  currentKey.current = requestKey
  const [previewKey, setPreviewKey] = useState('')
  const ready = preview !== null && previewKey === requestKey

  useEffect(() => {
    let active = true
    request<ExportDefinition[]>('get_export_definitions', {}).then(catalog => {
      if (!active) return
      setDefinitions(catalog)
    }).catch(error => { if (active) useApp.getState().setError(error) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    generation.current++
    setPreview(null)
    setWorking(false)
  }, [caseId, state.reportFormat, redacted])
  useEffect(() => { setPath('') }, [caseId, state.reportFormat])
  useEffect(() => () => { generation.current++ }, [])

  const makePreview = async () => {
    const ticket = ++generation.current
    setWorking(true)
    setPreview(null)
    setProgress('Starting report preparation…')
    let activeToken = ''
    try {
      let result = await request<Preview | Preparation>('preview_export', {
        case_id: caseId, format: state.reportFormat, redacted, progressive: true,
      })
      while ('preparation_token' in result) {
        const token = result.preparation_token
        activeToken = token
        if (ticket !== generation.current || currentKey.current !== requestKey) {
          await request('cancel_export_preview', { preparation_token: token })
          return
        }
        preparation.current = token
        setProgress(`Preparing ${result.stage.replaceAll('_', ' ')} · ${result.processed.toLocaleString()} entries processed`)
        await new Promise(resolve => setTimeout(resolve, 30))
        if (ticket !== generation.current) {
          await request('cancel_export_preview', { preparation_token: token })
          return
        }
        result = await request<Preview | Preparation>('export_preview_status', { preparation_token: token })
      }
      if (ticket === generation.current && currentKey.current === requestKey) {
        setPreview(result)
        setPreviewKey(requestKey)
      } else if (activeToken) {
        await request('cancel_export_preview', { preparation_token: activeToken })
      }
    } catch (error) { if (ticket === generation.current) state.setError(error) }
    finally {
      if (ticket === generation.current) { setWorking(false); preparation.current = '' }
    }
  }
  const cancelPreparation = () => {
    const token = preparation.current
    generation.current++
    preparation.current = ''
    setWorking(false)
    if (token) void request('cancel_export_preview', { preparation_token: token }).catch(state.setError)
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
      if (chosen && currentKey.current === requestKey) setPath(chosen)
    } catch (error) { state.setError(error) }
  }
  const save = async () => {
    if (!ready || !preview) return
    const ticket = ++generation.current
    setWorking(true)
    try {
      const result = await request<{ path: string }>('export_case', {
        case_id: caseId, format: state.reportFormat, path, redacted,
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
  const disabled = working || state.busy || !state.pipelineComplete || definitions.length === 0
  return <div className="grid items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
    <form className="space-y-5 rounded-md border border-line bg-panel p-5"
      onSubmit={event => { event.preventDefault(); void save() }}>
      <fieldset disabled={disabled} className="space-y-3">
        <legend className="mb-3 text-sm font-semibold">Format</legend>
        <div className="flex overflow-hidden rounded border border-line-input">
          {definitions.map(({ format }) => <button key={format} type="button"
            aria-pressed={state.reportFormat === format} onClick={() => state.setFormat(format)}
            className={`flex-1 border-r border-line-input py-2 text-xs last:border-r-0 ${state.reportFormat === format ? 'bg-ink font-semibold text-white' : 'bg-panel text-muted'}`}>
            {format}
          </button>)}
        </div>
      </fieldset>
      <p className="text-xs leading-relaxed text-muted">{definitions.find(definition => definition.format === state.reportFormat)?.description}</p>
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
        : 'Includes original identifiers and sensitive metadata. JSON retains all evidence values; PDF presents grouped summaries.'}</p>
      <button type="button" className={`${navigationButton} w-full justify-center`}
        disabled={disabled} onClick={() => { void makePreview() }}>
        {working ? 'Preparing…' : ready ? 'Refresh preview' : 'Preview export'}
      </button>
      {!state.pipelineComplete && <p className="text-xs text-muted">Complete the pipeline before previewing or exporting.</p>}
      <label className="block text-xs font-semibold">{`New ${state.reportFormat} file path`}
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
          <button type="button" className={navigationButton} disabled={disabled || preview.page >= preview.pages}
            onClick={() => { void turnPage(preview.page + 1) }}>Next</button>
        </nav>}
      </div>
      {ready && preview ? <>
        <div className="mb-4 space-y-2 text-xs text-muted">
          <p>Prepared {preview.format}: {(preview.size_bytes / (1024 * 1024)).toFixed(2)} MB</p>
          {redacted && <p>Pseudonymized sharing copy. Unsuitable for independent reanalysis.</p>}
          <details><summary className="cursor-pointer">Coverage counts</summary>
            <table className="mt-2 w-full text-left text-[11px]"><thead><tr><th>Data</th><th>Count</th></tr></thead>
              <tbody>{Object.entries(preview.counts).map(([name, count]) => <tr key={name}>
                <td className="pr-3">{name.replaceAll('_', ' ')}</td>
                <td>{typeof count === 'number' ? count : count.included}</td>
              </tr>)}</tbody></table>
          </details>
        </div>
        {preview.format === 'PDF' ? <>
          <label className="mb-3 flex items-center gap-2 text-xs">Zoom
            <select value={zoom} onChange={event => setZoom(Number(event.target.value))}
              className="rounded border border-line-input bg-panel p-1">
              {[0.75, 1, 1.25, 1.5].map(value => <option key={value} value={value}>{value * 100}%</option>)}
            </select>
          </label>
          <Suspense fallback={<p role="status">Loading PDF viewer?</p>}>
            <PdfPreview token={preview.preview_token} size={preview.size_bytes} page={preview.page}
              zoom={zoom} onError={error => { setPreview(null); state.setError(error) }} />
          </Suspense>
        </> : <div data-testid="export-preview-content" className="space-y-3 text-sm">
          <h3 className="font-semibold">Full case JSON</h3>
          <p>Includes all unique evidence observations, Exact and Strong comparisons, complete histories,
            events, findings and provenance. Repeated data is stored once through canonical references.</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
            <dt>Case</dt><dd>{preview.manifest.case_id}</dd>
            <dt>Prepared</dt><dd>{preview.manifest.exported_at}</dd>
            <dt>Engine revision</dt><dd>{preview.manifest.engine_revision}</dd>
            <dt>Analysis version</dt><dd>{preview.manifest.analysis_format_version}</dd>
          </dl>
        </div>}
      </> : <div className="py-24 text-center text-sm text-muted" role="status">
        {working ? <><p>{progress || 'Preparing the selected report…'}</p>
          <button type="button" className={navigationButton} onClick={cancelPreparation}>Cancel preparation</button>
        </> : 'Select Preview export to review the full JSON manifest or rendered PDF.'}
      </div>}
    </section>
  </div>
}
