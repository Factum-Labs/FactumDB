import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist'
import { request } from '../lib/backend'

const assets = new URL('/pdf-assets/', window.location.href).href
GlobalWorkerOptions.workerSrc = `${assets}pdf.worker.min.mjs`

export function PdfPreview({ token, size, page, zoom, onPageChange, onError }: {
  token: string; size: number; page: number; zoom: number; onPageChange: (page: number) => void; onError: (error: unknown) => void
}) {
  const scrollRoot = useRef<HTMLDivElement>(null)
  const currentPage = useRef(page)
  const [pageSize, setPageSize] = useState({ width: 595, height: 842 })
  const [viewerSize, setViewerSize] = useState({ width: 595, height: 600 })
  const scale = zoom || Math.max(0.05, Math.min(
    (viewerSize.width - 28) / pageSize.width, (viewerSize.height - 28) / pageSize.height,
  ))
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const errorHandler = useRef(onError)
  errorHandler.current = onError

  useEffect(() => {
    const root = scrollRoot.current
    if (!root) return
    const measure = () => setViewerSize({ width: root.clientWidth, height: root.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let active = true
    let loaded: PDFDocumentProxy | null = null
    let loading: ReturnType<typeof getDocument> | null = null
    setDocument(null)
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
      const firstPage = await loaded.getPage(1)
      const viewport = firstPage.getViewport({ scale: 1 })
      if (active) { setPageSize({ width: viewport.width, height: viewport.height }); setDocument(loaded) }
      else await loading.destroy()
    }
    void load().catch(error => { if (active) errorHandler.current(error) })
    return () => {
      active = false
      if (loading) void loading.destroy()
    }
  }, [token, size])

  useEffect(() => {
    const root = scrollRoot.current
    if (!document || !root) return
    const target = root.querySelector<HTMLElement>(`[data-pdf-page="${page}"]`)
    if (target) {
      // Scroll only for navigation or zoom; scrolling itself updates currentPage first.
      if (currentPage.current !== page || previousZoom.current !== scale || previousDocument.current !== document)
        root.scrollTop += target.getBoundingClientRect().top - root.getBoundingClientRect().top - 12
      currentPage.current = page
      previousZoom.current = scale
      previousDocument.current = document
    }
  }, [document, page, scale])

  const previousZoom = useRef(scale)
  const previousDocument = useRef<PDFDocumentProxy | null>(null)
  const trackPage = () => {
    const root = scrollRoot.current
    if (!root || !document) return
    const marker = root.getBoundingClientRect().top + 40
    let visible = 1
    for (const child of root.querySelectorAll<HTMLElement>('[data-pdf-page]')) {
      if (child.getBoundingClientRect().top > marker) break
      visible = Number(child.dataset.pdfPage)
    }
    if (visible !== currentPage.current) {
      currentPage.current = visible
      onPageChange(visible)
    }
  }

  return <div ref={scrollRoot} onScroll={trackPage}
    className="h-[70vh] min-w-0 overflow-auto rounded border border-line bg-page p-3"
    role="region" aria-label="Scrollable PDF preview" tabIndex={0} aria-busy={!document}>
    {!document ? <p role="status" className="text-xs text-muted">Loading PDF...</p> :
      <div className="flex w-max min-w-full flex-col items-center gap-4">
        {Array.from({ length: document.numPages }, (_, index) => <PdfPage key={index + 1}
          document={document} page={index + 1} zoom={scale} pageSize={pageSize}
          root={scrollRoot.current!} onError={error => errorHandler.current(error)} />)}
      </div>}
  </div>
}

function PdfPage({ document, page, zoom, pageSize, root, onError }: {
  document: PDFDocumentProxy; page: number; zoom: number; pageSize: { width: number; height: number }
  root: HTMLDivElement; onError: (error: unknown) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [nearby, setNearby] = useState(false)
  const [dimensions, setDimensions] = useState(pageSize)
  const [rendering, setRendering] = useState(true)
  const [renderedPage, setRenderedPage] = useState(0)
  const errorHandler = useRef(onError)
  errorHandler.current = onError
  useEffect(() => {
    const observer = new IntersectionObserver(entries => setNearby(entries[0].isIntersecting),
      { root, rootMargin: '100% 0px' })
    if (container.current) observer.observe(container.current)
    return () => observer.disconnect()
  }, [root])
  useEffect(() => {
    if (!nearby || !canvas.current) return
    let active = true
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined
    setRendering(true)
    const render = async () => {
      const pdfPage = await document.getPage(page)
      if (!active || !canvas.current) return
      const viewport = pdfPage.getViewport({ scale: zoom })
      setDimensions({ width: viewport.width / zoom, height: viewport.height / zoom })
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
  }, [document, page, zoom, nearby])

  return <div ref={container} data-pdf-page={page} role="group" aria-label={`PDF page ${page}`}
    className="relative shrink-0 bg-white shadow-md" style={{ width: dimensions.width * zoom, height: dimensions.height * zoom }} aria-busy={nearby && rendering}>
    {nearby && <canvas ref={canvas} role="img" aria-label={`Report PDF page ${page}`}
      data-testid="pdf-preview-canvas" data-rendered-page={renderedPage} className="block" />}
  </div>
}
