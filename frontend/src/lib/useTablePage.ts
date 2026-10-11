import { useCallback } from 'react'
import { useApp } from '../store'

// Keep pagination across screen unmounts without sharing positions between cases or runs.
export function useTablePage(table: string, caseScoped = true): [number, (page: number) => void] {
  const scope = useApp(state => caseScoped
    ? JSON.stringify([state.data?.case.case_id, state.data?.run?.run_id])
    : 'global')
  const key = JSON.stringify([scope, table])
  const page = useApp(state => state.tablePages[key] ?? 0)
  const setPage = useCallback((value: number) => useApp.getState().setTablePage(key, value), [key])
  return [page, setPage]
}
