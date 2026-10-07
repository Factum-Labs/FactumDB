import { useEffect, useState } from 'react'
import { object, request, type Row } from './backend'

/** Keep the overview small; retrieve the complete saved object on selection. */
export function useAnalysisDetail(caseId: string | undefined, kind: string, summary: Row | undefined, deferred: boolean, field?: string) {
  const identity = kind === 'history' ? object(summary?.record).id : kind === 'comparison' ? summary?.record_id : summary?.id
  const key = JSON.stringify([caseId, kind, identity, field])
  const [loaded, setLoaded] = useState<{ key: string; detail?: Row; findings?: Row[]; error?: string }>()
  useEffect(() => {
    if (!deferred || !caseId || typeof identity !== 'string') return
    let active = true
    void request<{ detail: Row; findings: Row[] }>('get_analysis_detail', {
      case_id: caseId, kind, identity, ...(field === undefined ? {} : { field }),
    }).then(result => { if (active) setLoaded({ key, ...result }) })
      .catch(error => { if (active) setLoaded({ key, error: String(error) }) })
    return () => { active = false }
  }, [caseId, kind, identity, field, deferred, key, summary])
  const current = loaded?.key === key ? loaded : undefined
  return {
    detail: deferred ? current?.detail : summary,
    findings: current?.findings ?? [],
    error: current?.error,
  }
}
