import { useEffect, useState } from 'react'
import { request, object, type CaseData, type HistoryPage, type HistoryTables } from './backend'
import { useApp } from '../store'

const located = new Map<string, number>()
let lastCase: string | undefined
const saved = new Map<string, { filter: string; offset: number }>()
export function useHistoryPage(data: CaseData | null) {
  const caseId = data?.case.case_id
  const navigation = useApp(s => s.recordNavigation)
  const [query, setQuery] = useState(() => {
    if (lastCase !== caseId) saved.clear()
    lastCase = caseId
    return { caseId, ...(saved.get(caseId ?? '') ?? { filter: '', offset: 0 }) }
  })
  const [tables, setTables] = useState<HistoryTables['tables']>([])
  const [result, setResult] = useState<HistoryPage>({ items: data?.analysis.reconstruction?.details_deferred === false ? (data.analysis.reconstruction.histories as HistoryPage['items'] ?? []) : [], total: 0, offset: 0, limit: 100 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (lastCase !== caseId) { saved.clear(); lastCase = caseId }
    setQuery(q => q.caseId === caseId ? q : { caseId, filter: '', offset: 0 })
  }, [caseId])
  useEffect(() => {
    if (!caseId || query.caseId !== caseId) return
    let active = true
    setLoading(true); setError(''); setResult({ items: [], total: 0, offset: query.offset, limit: 100 })
    const load = async () => {
      const target = useApp.getState().selectedRecord
      if (navigation && target && located.get(caseId) !== navigation) {
        const location = await request<{ table: string; offset: number }>('locate_history_record', { case_id: caseId, identity: target })
        if (!active) return
        located.set(caseId, navigation)
        setQuery({ caseId, filter: location.table, offset: location.offset })
        return
      }
      const options = await request<HistoryTables>('get_history_tables', { case_id: caseId })
      const table = options.tables.find(t => t.table === query.filter)
      if (query.filter && !table) { setTables(options.tables); setResult({ items: [], total: 0, offset: 0, limit: 100 }); return }
      const page = await request<HistoryPage>('get_history_page', { case_id: caseId, offset: query.offset, limit: 100, ...(table ? { database: table.database, table: table.table } : {}) })
      if (!active) return
      if (query.offset > 0 && !page.items.length) { setQuery(q => ({ ...q, offset: 0 })); return }
      setTables(options.tables); setResult(page)
      saved.set(caseId, { filter: query.filter, offset: query.offset })
      const selection = useApp.getState()
      if (!page.items.some(h => object(h.record).id === selection.selectedRecord && (!selection.selectedRecordTable || object(h.record).table === selection.selectedRecordTable))) useApp.getState().selectRecord(String(object(page.items[0]?.record).id ?? ''), String(object(page.items[0]?.record).table ?? ''))
    }
    void load().catch(e => { if (active) setError(String(e)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [caseId, data, query, navigation])
  return { ...result, tables, loading, error, filter: query.filter,
    changeFilter: (filter: string) => { useApp.getState().selectRecord(''); setQuery({ caseId, filter, offset: 0 }) },
    changePage: (offset: number) => { useApp.getState().selectRecord(''); setQuery(q => ({ ...q, offset })) } }
}
