import assert from 'node:assert/strict'
import { CasePreviewController } from '../src/lib/casePreviewController'
import type { CasePreview } from '../src/lib/backend'

const calls: string[] = []
const waiting: { resolve: (value: unknown) => void; reject: (reason: unknown) => void }[] = []
const controller = new CasePreviewController(<T>(command: string, payload: Record<string, unknown>) => {
  calls.push(`${command}:${payload.case_id}`)
  return new Promise<T>((resolve, reject) => waiting.push({ resolve: value => resolve(value as T), reject }))
})
const preview = (id: string) => ({ case: { case_id: id }, pipeline: {}, evidence: [], run: null }) as unknown as CasePreview
const tick = async () => { await new Promise(resolve => setTimeout(resolve, 0)) }
controller.prefetch(['newest', 'middle', 'oldest'])
assert.deepEqual(calls, ['get_case_header:newest'])
const oldest = controller.preview('oldest', true)
assert.equal(controller.preview('oldest'), oldest)
waiting.shift()!.resolve(preview('newest')); await tick()
assert.deepEqual(calls, ['get_case_header:newest', 'get_case_header:oldest'])
waiting.shift()!.resolve(preview('oldest')); await oldest; await tick()
assert.equal(calls.at(-1), 'get_case_header:middle')
assert.equal(await controller.preview('oldest'), controller.cached('oldest'))
const full = controller.full('oldest', () => true)
waiting.shift()!.resolve(preview('middle')); await tick()
assert.equal(calls.at(-1), 'get_case_data:oldest')
waiting.shift()!.resolve({ case: { case_id: 'oldest' } }); await full; await tick()
controller.invalidate('oldest')
assert.equal(controller.cached('oldest'), undefined)
const failed = controller.preview('oldest', true)
const caught = assert.rejects(failed, /unavailable/)
waiting.shift()!.reject(new Error('unavailable')); await caught; await tick()
const retry = controller.preview('oldest', true)
waiting.shift()!.resolve(preview('oldest')); await retry; await tick()
const stale = controller.preview('stale')
controller.prefetch(['queued'])
controller.clear()
waiting.shift()!.resolve(preview('stale'))
assert.equal(await stale, undefined); await tick()
assert.equal(controller.cached('stale'), undefined)
assert.ok(!calls.some(call => call.endsWith(':queued')))
const replaced = controller.preview('replaced')
controller.invalidate('replaced')
waiting.shift()!.resolve(preview('replaced'))
assert.equal(await replaced, undefined); await tick()
const skipped = controller.full('oldest', () => false)
assert.equal(await skipped, undefined)
console.log('Case preview controller checks passed: ordering, priority, deduplication, sequential dispatch, failure retry, mutation and session guards.')
