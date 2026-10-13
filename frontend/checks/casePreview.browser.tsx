// The current preview browser check also exercises independent screen loading.
import './progressive.browser'
import { CasePreviewController } from '../src/lib/casePreviewController'
import type { CasePreview } from '../src/lib/backend'

let memoryController: CasePreviewController | undefined
Object.assign(window, { loadPreviewMemory: async () => {
  memoryController = new CasePreviewController(async <T,>(_command: string, payload: Record<string, unknown>) => {
    const result = await (await fetch('/measured-preview.json')).json() as CasePreview
    result.case.case_id = String(payload.case_id)
    return result as T
  })
  memoryController.prefetch(Array.from({length:20},(_,n)=>`case-${n}`))
  await memoryController.preview('case-19')
  return { retained_cases: 20 }
} })
