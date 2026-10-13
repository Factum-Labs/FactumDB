import { useCallback, useEffect, useMemo, useState } from 'react'
import { type CaseData, type HistoryTables, type Row } from './backend'
import { useScreenQuery, useNextPage, type ScreenPage } from './useScreenQuery'
import { useTablePage } from './useTablePage'
import { useApp } from '../store'

const filters = new Map<string, string>()
useApp.subscribe((state, previous) => {
  if (state.caseOpening !== previous.caseOpening || state.locked || !state.user) filters.clear()
})

/** Indexed summaries first; only the selected history needs its replay details. */
export function useHistoryPage(data: CaseData | null) {
  const opening = useApp(s => s.caseOpening)
  const scope = `${opening}:${data?.case.case_id ?? ''}`
  const [filter, setFilter] = useState(() => filters.get(scope) ?? '')
  const [page, setPage] = useTablePage('history-list')
  const selected = useApp(s => s.selectedRecord)
  const table = useApp(s => s.selectedRecordTable)
  const navigation = useApp(s => s.recordNavigation)
  const [located, setLocated] = useState(0)
  const active = useApp(s => s.screen === 'record' && !s.locked)
  useEffect(() => { setFilter(filters.get(scope) ?? ''); setLocated(0) }, [scope])
  const changeFilter = useCallback((value: string) => {
    filters.set(scope, value)
    if (filters.size > 16) filters.delete(filters.keys().next().value!)
    setFilter(value)
  }, [scope])
  const legacy = Array.isArray(data?.analysis.reconstruction?.histories) && data?.analysis.reconstruction?.details_deferred !== true
  const tables = useScreenQuery<HistoryTables>('get_history_tables', {}, 'record', !legacy)
  const payload = { kind: 'histories', offset: page * 100, limit: 100, ...(filter ? { bucket: filter } : {}) }
  const query = useScreenQuery<ScreenPage>('get_screen_page', payload, 'record', !legacy)
  useNextPage(query.value, payload, 'record')
  const location = useScreenQuery<{ table: string; offset: number }>('locate_history_record', { identity: selected, ...(table ? { qualified_table: table } : {}) }, 'record', !!selected && navigation !== located && !legacy)
  useEffect(() => {
    if (location.value && navigation !== located) {
      changeFilter(location.value.table); setPage(location.value.offset / 100); setLocated(navigation)
    }
  }, [location.value, navigation, located, setPage, changeFilter])
  const items = useMemo(() => legacy ? (data?.analysis.reconstruction?.histories as Row[] ?? []) : query.value?.items ?? [], [legacy, data?.analysis.reconstruction?.histories, query.value?.items])
  const shownItems = useMemo(() => legacy ? items.slice(page*100,(page+1)*100) : items,[legacy,items,page])
  useEffect(() => {
    if (!active || !shownItems.length || (legacy && selected) || (selected && navigation !== located)) return
    if (!shownItems.some(item => item.record && (item.record as Row).id === selected)) {
      const record = shownItems[0].record as Row
      useApp.getState().selectRecord(String(record.id), String(record.table))
    }
  }, [active, shownItems, selected, navigation, located, legacy])
  const summaryItems = legacy ? shownItems.map(detail => ({ summary: detail, detail, findings: [] }))
    : shownItems.map(summary => ({ summary, detail: undefined, findings: [] }))
  return { items: summaryItems, total: legacy ? items.length : query.value?.total ?? 0, offset: page * 100, limit: 100,
    tables: tables.value?.tables ?? [], loading: !legacy && query.loading, error: query.error || tables.error || location.error,
    retry: query.retry, filter, changeFilter: (value: string) => { changeFilter(value); setPage(0); useApp.getState().selectRecord('') },
    changePage: (offset: number) => { setPage(offset / 100); if (!legacy) useApp.getState().selectRecord('') } }
}
