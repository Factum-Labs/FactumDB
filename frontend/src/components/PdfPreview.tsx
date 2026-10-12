import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist'
import { request } from '../lib/backend'

const assets = new URL('/pdf-assets/', window.location.href).href
GlobalWorkerOptions.workerSrc = `${assets}pdf.worker.min.mjs`

export function PdfPreview({ token, size, page, zoom, onError }: {
  token: string; size: number; page: number; zoom: number; onError: (error: unknown) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [rendering, setRendering] = useState(true)
  const [renderedPage, setRenderedPage] = useState(0)
  const errorHandler = useRef(onError)
  errorHandler.current = onError

  useEffect(() => {
    let active = true
    let loaded: PDFDocumentProxy | null = null
    let loading: ReturnType<typeof getDocument> | null = null
    setDocument(null)
    setRenderedPage(0)
    setRendering(true)
    const load = async () => {
      const data = new Uint8Array(size)
      for (let offset = 0; offset < size;) {
        const chunk = await request<{ data: string; offset: number; total_bytes: number }>(
          'export_preview_pdf', { preview_token: token, offset, length: Math.min(262144, size - offset) },
        )
        if (!active) return
        const decoded = Uint8Array.from(atob(chunk.data), character => character.charCodeAt(0))
        if (chunk.offset !== offset || chunk.total_bytes !== size || decoded.length === 0 || decoded.length > size - offset)
          throw new Error('The prepared PDF changed; refresh the preview.')
        data.set(decoded, offset)
        offset += decoded.length
      }
      if (!active) return
      loading = getDocument({ data, cMapUrl: `${assets}cmaps/`, cMapPacked: true,
        standardFontDataUrl: `${assets}standard_fonts/`, wasmUrl: `${assets}wasm/`,
        useSystemFonts: false })
      loaded = await loading.promise
      if (active) setDocument(loaded)
      else await loading.destroy()
    }
    void load().catch(error => { if (active) errorHandler.current(error) })
    return () => {
      active = false
      if (loading) void loading.destroy()
    }
  }, [token, size])

  useEffect(() => {
    if (!document || !canvas.current) return
    let active = true
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined
    setRendering(true)
    const render = async () => {
      const pdfPage = await document.getPage(page)
      if (!active || !canvas.current) return
      const viewport = pdfPage.getViewport({ scale: zoom })
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const target = canvas.current
      target.width = Math.ceil(viewport.width * ratio)
      target.height = Math.ceil(viewport.height * ratio)
      target.style.width = `${viewport.width}px`
      target.style.height = `${viewport.height}px`
      renderTask = pdfPage.render({ canvas: target, viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] })
      await renderTask.promise
      if (active) { setRendering(false); setRenderedPage(page) }
    }
    void render().catch(error => {
      if (active && error?.name !== 'RenderingCancelledException') errorHandler.current(error)
    })
    return () => { active = false; renderTask?.cancel() }
  }, [document, page, zoom])

  return <div className="overflow-auto rounded border border-line bg-page p-3" aria-busy={rendering}>
    {rendering && <p role="status" className="mb-2 text-xs text-muted">Rendering PDF page…</p>}
    <canvas ref={canvas} role="img" aria-label={`Report PDF page ${page}`}
      data-testid="pdf-preview-canvas" data-rendered-page={renderedPage}
      className="mx-auto bg-white shadow-md" />
  </div>
}
