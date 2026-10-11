import { useEffect, useRef, useState } from 'react'
import { request, object, type CaseData, type BundledHistoryPage, type HistoryTables, type Row } from './backend'
import { HistoryPageController, ObsoleteHistoryRequest } from './historyPageController'
import { useApp } from '../store'

const located = new Map<string, number>()
let lastCase: string | undefined
const saved = new Map<string, { filter: string; offset: number }>()
const emptyPage = (offset = 0): BundledHistoryPage => ({ items: [], total: 0, offset, limit: 100 })

function selectPage(page: BundledHistoryPage) {
  const selection = useApp.getState()
  if (!page.items.some(h => object(h.summary.record).id === selection.selectedRecord &&
    (!selection.selectedRecordTable || object(h.summary.record).table === selection.selectedRecordTable))) {
    const record = object(page.items[0]?.summary.record)
    selection.selectRecord(String(record.id ?? ''), String(record.table ?? ''))
  }
}

export function useHistoryPage(data: CaseData | null) {
  const caseId = data?.case.case_id
  const navigation = useApp(s => s.recordNavigation)
  const locked = useApp(s => s.locked)
  const snapshot = useRef({ data, generation: 0 })
  if (snapshot.current.data !== data) snapshot.current = { data, generation: snapshot.current.generation + 1 }
  const generation = snapshot.current.generation
  const [controller] = useState(() => new HistoryPageController((scope, offset) =>
    request<BundledHistoryPage>('get_history_page', { case_id: scope.caseId, offset, limit: 100, include_details: true,
      ...(scope.table ? { database: scope.database, table: scope.table } : {}) })))
  const [query, setQuery] = useState(() => {
    if (lastCase !== caseId) saved.clear()
    lastCase = caseId
    return { caseId, ...(saved.get(caseId ?? '') ?? { filter: '', offset: 0 }) }
  })
  const [tables, setTables] = useState<HistoryTables['tables']>([])
  const [shown, setShown] = useState<{ data: CaseData | null; filter: string; page: BundledHistoryPage }>(() => {
    const items = data?.analysis.reconstruction?.details_deferred === false
      ? (data.analysis.reconstruction.histories as Row[] ?? []).map(detail => ({ summary: detail, detail, findings: [] })) : []
    return { data, filter: query.filter, page: { ...emptyPage(), items, total: items.length } }
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => () => controller.dispose(), [controller])
  useEffect(() => {
    if (lastCase !== caseId) { saved.clear(); located.clear(); lastCase = caseId }
    setQuery(q => q.caseId === caseId ? q : { caseId, filter: '', offset: 0 })
  }, [caseId])
  useEffect(() => {
    if (!caseId || query.caseId !== caseId || locked) {
      controller.dispose()
      setShown({ data, filter: query.filter, page: emptyPage(query.offset) })
      setLoading(false)
      return
    }
    let active = true
    setError('')
    // Invalidate queued work before waiting for table options or record location.
    const knownTable = tables.find(t => t.table === query.filter)
    controller.activate({ caseId, generation, ...(query.filter ? { database: knownTable?.database, table: query.filter } : {}) }, query.offset)
    const cached = controller.peek(query.offset)
    const target = useApp.getState().selectedRecord
    const locating = navigation && target && located.get(caseId) !== navigation
    setLoading(!cached || !!locating)
    if (cached && !locating) { setShown({ data, filter: query.filter, page: cached }); selectPage(cached) }
    else setShown({ data, filter: query.filter, page: emptyPage(query.offset) })
    const load = async () => {
      if (locating) {
        const location = await request<{ table: string; offset: number }>('locate_history_record', { case_id: caseId, identity: target })
        if (!active) return
        located.set(caseId, navigation)
        setQuery({ caseId, filter: location.table, offset: location.offset })
        return
      }
      const options = await controller.tables(caseId, generation, () => request<HistoryTables>('get_history_tables', { case_id: caseId }))
      if (!active) return
      setTables(options.tables)
      const table = options.tables.find(t => t.table === query.filter)
      if (query.filter && !table) {
        setShown({ data, filter: query.filter, page: emptyPage() })
        useApp.getState().selectRecord('')
        return
      }
      controller.activate({ caseId, generation, ...(table ? { database: table.database, table: table.table } : {}) }, query.offset)
      const page = await controller.load(query.offset)
      if (!active) return
      if (query.offset > 0 && !page.items.length) { setQuery(q => ({ ...q, offset: 0 })); return }
      setShown({ data, filter: query.filter, page })
      saved.set(caseId, { filter: query.filter, offset: query.offset })
      selectPage(page)
    }
    void load().catch(e => { if (active && !(e instanceof ObsoleteHistoryRequest)) setError(String(e)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [caseId, data, generation, query, navigation, locked, controller, tables])

  const visible = !locked && query.caseId === caseId && shown.data === data && shown.filter === query.filter && shown.page.offset === query.offset
  const result = visible ? shown.page : emptyPage(query.offset)
  useEffect(() => {
    if (!visible || loading || error || !result.items.length) return
    // The first frame commits the page; the second allows its paint before IPC.
    let second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => { void controller.prefetch(result.total) })
    })
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second) }
  }, [visible, loading, error, result, controller])

  return { ...result, tables, loading, error, filter: query.filter,
    changeFilter: (filter: string) => {
      const table = tables.find(t => t.table === filter)
      controller.activate({ caseId: caseId ?? '', generation, ...(filter ? { database: table?.database, table: filter } : {}) }, 0)
      setShown({ data, filter, page: emptyPage() })
      setLoading(true); setError(''); useApp.getState().selectRecord('')
      setQuery({ caseId, filter, offset: 0 })
    },
    changePage: (offset: number) => {
      const table = tables.find(t => t.table === query.filter)
      controller.activate({ caseId: caseId ?? '', generation, ...(table ? { database: table.database, table: table.table } : {}) }, offset)
      const page = controller.peek(offset)
      useApp.getState().selectRecord('')
      setError(''); setLoading(!page)
      if (page) { setShown({ data, filter: query.filter, page }); selectPage(page) }
      else setShown({ data, filter: query.filter, page: emptyPage(offset) })
      setQuery(q => ({ ...q, offset }))
    } }
}
