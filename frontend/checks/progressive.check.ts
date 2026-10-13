import assert from 'node:assert/strict'
import { RequestLane, ObsoleteRequest } from '../src/lib/requestLane'
import { reportProgress } from '../src/lib/reportProgress'
import { ScreenCache } from '../src/lib/screenCache'

const lane = new RequestLane()
const dispatched: string[] = []
let release!: () => void
const running = lane.enqueue(() => new Promise<void>(resolve => { dispatched.push('running'); release = resolve }))
await Promise.resolve()
const background = lane.enqueue(async () => { dispatched.push('background') }, true)
const obsolete = lane.enqueue(async () => { dispatched.push('obsolete') }, true, () => false).catch(e => e)
const foreground = lane.enqueue(async () => { dispatched.push('foreground') })
release()
await Promise.all([running, background, foreground])
assert.deepEqual(dispatched, ['running', 'foreground', 'background'])
assert.ok(await obsolete instanceof ObsoleteRequest)

// Adjacent pages precede the opening warm-up; navigation promotes a queued page.
const prioritized = new RequestLane()
const order: string[] = []
let unblock!: () => void
const blocker = prioritized.enqueue(() => new Promise<void>(resolve => { unblock = resolve }))
await Promise.resolve()
const warmOne = prioritized.enqueue(async () => { order.push('warm-one') }, true, undefined, 'one', 2)
const warmTwo = prioritized.enqueue(async () => { order.push('visible') }, true, undefined, 'two', 2)
const adjacent = prioritized.enqueue(async () => { order.push('next-page') }, true, undefined, 'next', 1)
prioritized.promote('two')
unblock()
await Promise.all([blocker, warmOne, warmTwo, adjacent])
assert.deepEqual(order, ['visible', 'next-page', 'warm-one'])

// A later navigation/page job overtakes dependency warm-up during its idle wait.
const idleLane = new RequestLane()
const idleOrder: string[] = []
const dependency = idleLane.enqueue(async () => { idleOrder.push('dependencies') }, true, undefined, undefined, 3)
await new Promise(resolve => setTimeout(resolve, 25))
const latePage = idleLane.enqueue(async () => { idleOrder.push('late-page') }, true, undefined, undefined, 2)
const navigation = idleLane.enqueue(async () => { idleOrder.push('navigation') })
await Promise.all([dependency, latePage, navigation])
assert.deepEqual(idleOrder, ['navigation', 'late-page', 'dependencies'])

// Report batches remain below dependency imports and subsequently queued pages.
const reportLane = new RequestLane()
const reportOrder: string[] = []
let releaseReport!: () => void
const runningReport = reportLane.enqueue(() => new Promise<void>(resolve => { releaseReport = resolve }))
await Promise.resolve()
const render = reportLane.enqueue(async () => { reportOrder.push('report') }, true, undefined, undefined, 4)
const imports = reportLane.enqueue(async () => { reportOrder.push('imports') }, true, undefined, undefined, 3)
const newPage = reportLane.enqueue(async () => { reportOrder.push('new-page') }, true, undefined, undefined, 1)
releaseReport()
await Promise.all([runningReport, render, imports, newPage])
assert.deepEqual(reportOrder, ['new-page', 'imports', 'report'])

// A continuing report stream pays the idle grace period once, not per batch.
const continuous = new RequestLane()
const started = performance.now()
for (let batch = 0; batch < 12; batch++) await continuous.enqueue(async () => {}, true, undefined, undefined, 4)
assert.ok(performance.now() - started < 1000, 'Report batches must not each wait 250 ms')

// Keepalive reads still run, but cannot re-arm the grace period mid-report stream.
const keepaliveLane = new RequestLane()
const keepaliveStart = performance.now()
for (let batch = 0; batch < 12; batch++) {
  await keepaliveLane.enqueue(async () => {}, true, undefined, undefined, 4)
  await keepaliveLane.enqueue(async () => {}, false, undefined, undefined, 1, true)
}
assert.ok(performance.now() - keepaliveStart < 1000, 'Authentication polling must not repeat report idle waits')
assert.ok(reportProgress('reading_reconciliation', 213975040, 'bytes').includes('MB'))
assert.ok(!reportProgress('reading_reconciliation', 213975040, 'bytes').includes('entries'))

const cache = new ScreenCache(100, 2)
let fetches = 0
const load = () => { fetches++; return Promise.resolve('payload') }
assert.deepEqual(await Promise.all([cache.load('same', load), cache.load('same', load)]), ['payload', 'payload'])
assert.equal(fetches, 1)
await cache.load('second', load)
cache.peek('same')
await cache.load('third', load)
assert.equal(cache.peek('second'), undefined)
assert.ok(cache.size().bytes <= 100)
let finish!: (value: string) => void
const late = cache.load('late', () => new Promise<string>(resolve => { finish = resolve }))
cache.clear(); finish('secret'); await late
assert.equal(cache.peek('late'), undefined)
assert.equal(cache.size().entries, 0)
console.log('Progressive cache and request priority checks passed')
