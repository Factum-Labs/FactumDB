import { useCallback } from 'react'
import { useApp } from '../store'

// Keep pagination across screen unmounts within the current case opening.
export function useTablePage(table: string, caseScoped = true): [number, (page: number) => void] {
  const scope = useApp(state => caseScoped
    ? JSON.stringify([state.caseOpening, state.activeCaseId ?? state.data?.case.case_id, state.preview?.run?.run_id ?? state.data?.run?.run_id])
    : 'global')
  const key = JSON.stringify([scope, table])
  const page = useApp(state => state.tablePages[key] ?? 0)
  const setPage = useCallback((value: number) => useApp.getState().setTablePage(key, value), [key])
  return [page, setPage]
}
