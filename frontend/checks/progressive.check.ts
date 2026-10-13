import assert from 'node:assert/strict'
import { RequestLane, ObsoleteRequest } from '../src/lib/requestLane'
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
