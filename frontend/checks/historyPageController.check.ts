import assert from 'node:assert/strict'
import { HistoryPageController, HistoryPageLane, ObsoleteHistoryRequest } from '../src/lib/historyPageController'
import type { BundledHistoryPage } from '../src/lib/backend'

const scope = { caseId: 'case-a', generation: 0 }
const page = (offset: number, total = 405): BundledHistoryPage => ({ items: [], offset, total, limit: 100 })
const tick = () => new Promise<void>(resolve => setImmediate(resolve))
function fixture() {
  const calls: { caseId: string; table?: string; offset: number; resolve: (page: BundledHistoryPage) => void; reject: (error: Error) => void }[] = []
  const lane = new HistoryPageLane()
  const controller = new HistoryPageController((scope, offset) => new Promise((resolve, reject) => {
    calls.push({ ...scope, offset, resolve, reject })
  }), lane)
  controller.activate(scope, 0)
  return { controller, calls, lane }
}

{
  const { controller, calls } = fixture()
  const first = controller.load(0)
  assert.equal(first, controller.load(0), 'Deduplicate foreground requests')
  await tick()
  assert.deepEqual(calls.map(c => c.offset), [0], 'No implicit prefetch before display')
  calls[0].resolve(page(0)); await first
  const background = controller.prefetch(405)
  await tick()
  const next = controller.load(100)
  assert.equal(calls.length, 2, 'Reuse active prefetch for foreground navigation')
  controller.activate(scope, 100)
  calls[1].resolve(page(100)); await next; await background
  assert.deepEqual(controller.cachedOffsets(), [0, 100])
  const adjacent = controller.prefetch(405)
  await tick(); calls[2].resolve(page(200)); await adjacent
  assert.deepEqual(calls.map(c => c.offset), [0, 100, 200], 'Previous page is never refetched')
  controller.activate(scope, 200)
  assert.deepEqual(controller.cachedOffsets(), [100, 200], 'Evict outside window on navigation')
  const more = controller.prefetch(405)
  await tick(); calls[3].resolve(page(300)); await more
  assert.deepEqual(controller.cachedOffsets(), [100, 200, 300])
  controller.activate(scope, 100)
  const back = controller.prefetch(405)
  await tick(); assert.equal(calls[4].offset, 0)
  calls[4].resolve(page(0)); await back
  assert.deepEqual(controller.cachedOffsets(), [0, 100, 200])
  controller.dispose(); assert.deepEqual(controller.cachedOffsets(), [])
}

{
  const { controller, calls } = fixture()
  controller.activate(scope, 200)
  const middle = controller.load(200)
  await tick(); calls[0].resolve(page(200)); await middle
  const neighbors = controller.prefetch(405)
  await tick(); assert.equal(calls[1].offset, 300)
  calls[1].resolve(page(300)); await tick()
  assert.equal(calls[2].offset, 100, 'Direct jump loads missing previous after next')
  calls[2].resolve(page(100)); await neighbors
  assert.deepEqual(controller.cachedOffsets(), [100, 200, 300])
  controller.activate(scope, 400)
  const last = controller.load(400)
  await tick(); calls[3].resolve(page(400)); await last
  await controller.prefetch(405)
  assert.equal(calls.length, 4, 'No page beyond the last page')
  controller.activate({ ...scope, generation: 1 }, 0)
  const empty = controller.load(0)
  await tick(); calls[4].resolve(page(0, 0)); await empty
  await controller.prefetch(0); assert.equal(calls.length, 5)
}

{
  const { controller, calls, lane } = fixture()
  const old = controller.load(0).catch(error => error)
  await tick()
  controller.activate({ ...scope, table: 'other.accounts', database: 'other' }, 0)
  const stale = controller.load(100, false).catch(error => error)
  const foreground = controller.load(0)
  calls[0].resolve(page(0)); assert.ok(await old instanceof ObsoleteHistoryRequest)
  await tick()
  assert.equal(calls[1].offset, 0, 'Foreground wins over unsent background')
  calls[1].resolve(page(0)); await foreground; await tick()
  assert.equal(calls[2].offset, 100)
  controller.dispose()
  const newController = new HistoryPageController(async (_, offset) => {
    calls.push({ caseId: 'case-b', offset, resolve: () => {}, reject: () => {} })
    return page(offset)
  }, lane)
  newController.activate({ caseId: 'case-b', generation: 0 }, 0)
  const nextCase = newController.load(0)
  await tick(); assert.equal(calls.length, 3, 'Remount waits for old active request')
  calls[2].resolve(page(100)); assert.ok(await stale instanceof ObsoleteHistoryRequest)
  await nextCase
  assert.deepEqual(controller.cachedOffsets(), [])
  assert.deepEqual(newController.cachedOffsets(), [0])
}

{
  const { controller, calls } = fixture()
  const current = controller.load(0)
  await tick(); calls[0].resolve(page(0)); await current
  const background = controller.prefetch(405)
  await tick(); calls[1].reject(new Error('Background failed')); await background
  assert.deepEqual(controller.cachedOffsets(), [0])
  await tick(); assert.equal(calls.length, 2, 'No automatic retry')
  controller.activate(scope, 100)
  const retry = controller.load(100)
  await tick(); calls[2].resolve(page(100)); await retry
  let optionsCalls = 0
  const options = async () => { optionsCalls++; return { tables: [], total: 0 } }
  await controller.tables('case-a', 0, options)
  controller.activate({ ...scope, table: 'credit.accounts' }, 0)
  await controller.tables('case-a', 0, options)
  assert.equal(optionsCalls, 1, 'Table options shared across filters')
  await controller.tables('case-a', 1, options); assert.equal(optionsCalls, 2)
}
{
  const { controller, calls } = fixture()
  const old = controller.load(0).catch(error => error)
  await tick()
  const queued = controller.load(100, false).catch(error => error)
  controller.activate(scope, 400)
  const jump = controller.load(400)
  calls[0].resolve(page(0)); assert.ok(await old instanceof ObsoleteHistoryRequest)
  await tick(); assert.equal(calls[1].offset, 400)
  calls[1].resolve(page(400)); await jump
  assert.ok(await queued instanceof ObsoleteHistoryRequest)
  assert.deepEqual(calls.map(call => call.offset), [0, 400], 'Obsolete queued work never reaches backend')
  assert.deepEqual(controller.cachedOffsets(), [400], 'Late obsolete page is not retained')
}
console.log('PASS: history cache reuse, deduplication, foreground priority, sequential prefetch, eviction, invalidation, rapid jumps, remount, failures and table options.')
