import { object, type Row } from './backend'
import { useScreenQuery } from './useScreenQuery'

/** Keep the overview small; retrieve the complete saved object on selection. */
export function useAnalysisDetail(caseId: string | undefined, kind: string, summary: Row | undefined, deferred: boolean, field?: string) {
  const identity = kind === 'history' ? object(summary?.record).id : kind === 'comparison' ? summary?.record_id : summary?.id
  const qualifiedTable = kind === 'history' ? object(summary?.record).table : undefined
  const screen = kind === 'history' ? 'record' : kind === 'transaction' ? 'timeline' : 'recon'
  const loaded = useScreenQuery<{ detail: Row; findings: Row[] }>('get_screen_detail', {
    kind: { history: 'histories', transaction: 'transactions', comparison: 'comparisons' }[kind], identity,
    ...(qualifiedTable ? { bucket: qualifiedTable } : {}), ...(field === undefined ? {} : { bucket: field }),
  }, screen, deferred && !!caseId && typeof identity === 'string')
  return {
    detail: deferred ? loaded.value?.detail : summary,
    findings: loaded.value?.findings ?? [],
    error: loaded.error,
    retry: loaded.retry,
  }
}
