import type { BundledHistoryPage, HistoryTables } from './backend'

export interface HistoryScope {
  caseId: string
  generation: number
  database?: string
  table?: string
}
type PageLoader = (scope: HistoryScope, offset: number) => Promise<BundledHistoryPage>
type Job = {
  foreground: boolean
  valid: () => boolean
  run: () => Promise<BundledHistoryPage>
  resolve: (page: BundledHistoryPage) => void
  reject: (error: unknown) => void
}

export class ObsoleteHistoryRequest extends Error {}

/** Shared across mounted controllers so an old in-flight request finishes first. */
export class HistoryPageLane {
  private jobs: Job[] = []
  private busy = false

  enqueue(run: Job['run'], valid: Job['valid'], foreground: boolean) {
    let job!: Job
    const promise = new Promise<BundledHistoryPage>((resolve, reject) => {
      job = { run, valid, foreground, resolve, reject }
      this.jobs.push(job)
    })
    queueMicrotask(() => this.pump())
    return { promise, promote: () => { job.foreground = true } }
  }

  private pump() {
    if (this.busy) return
    const priority = this.jobs.findIndex(job => job.foreground)
    const job = this.jobs.splice(priority < 0 ? 0 : priority, 1)[0]
    if (!job) return
    if (!job.valid()) {
      job.reject(new ObsoleteHistoryRequest())
      this.pump()
      return
    }
    this.busy = true
    void job.run().then(job.resolve, job.reject).finally(() => {
      this.busy = false
      this.pump()
    })
  }
}

const sharedLane = new HistoryPageLane()

/** Owns only the active scope's previous/current/next completed pages. */
export class HistoryPageController {
  private scope: HistoryScope | null = null
  private epoch = 0
  private center = 0
  private pages = new Map<number, BundledHistoryPage>()
  private pending = new Map<number, ReturnType<HistoryPageLane['enqueue']>>()
  private options: Promise<HistoryTables> | null = null
  private optionsGeneration = ''
  private loader: PageLoader
  private lane: HistoryPageLane

  constructor(loader: PageLoader, lane = sharedLane) {
    this.loader = loader
    this.lane = lane
  }

  activate(scope: HistoryScope, offset: number) {
    const same = this.scope && this.scope.caseId === scope.caseId &&
      this.scope.generation === scope.generation && this.scope.database === scope.database && this.scope.table === scope.table
    if (!same) {
      this.epoch++
      this.pages.clear()
      this.pending.clear()
      this.scope = scope
    }
    this.center = offset
    this.prune()
  }

  tables(caseId: string, generation: number, load: () => Promise<HistoryTables>) {
    const key = JSON.stringify([caseId, generation])
    if (key !== this.optionsGeneration) {
      this.optionsGeneration = key
      this.options = null
    }
    if (!this.options) {
      const options = load()
      this.options = options
      void options.catch(() => { if (this.options === options) this.options = null })
    }
    return this.options
  }

  peek(offset: number) { return this.pages.get(offset) }
  cachedOffsets() { return [...this.pages.keys()].sort((a, b) => a - b) }

  load(offset: number, foreground = true): Promise<BundledHistoryPage> {
    const cached = this.pages.get(offset)
    if (cached) return Promise.resolve(cached)
    const existing = this.pending.get(offset)
    if (existing) {
      if (foreground) existing.promote()
      return existing.promise
    }
    const scope = this.scope
    const epoch = this.epoch
    if (!scope) return Promise.reject(new ObsoleteHistoryRequest())
    const valid = () => this.epoch === epoch && !!this.scope && this.inWindow(offset)
    const queued = this.lane.enqueue(() => this.loader(scope, offset), valid, foreground)
    const pending = { ...queued, promise: queued.promise.then(page => {
      if (!valid()) throw new ObsoleteHistoryRequest()
      this.pages.set(offset, page)
      this.prune()
      return page
    }).finally(() => {
      if (this.pending.get(offset) === pending) this.pending.delete(offset)
    }) }
    this.pending.set(offset, pending)
    return pending.promise
  }

  async prefetch(total: number) {
    const epoch = this.epoch
    const center = this.center
    for (const offset of [center + 100, center - 100]) {
      if (epoch !== this.epoch || center !== this.center || !this.scope) return
      if (offset < 0 || offset >= total || this.pages.has(offset)) continue
      try { await this.load(offset, false) } catch { /* Navigation retries failures in the foreground. */ }
    }
  }

  dispose() {
    this.epoch++
    this.scope = null
    this.pages.clear()
    this.pending.clear()
    this.options = null
    this.optionsGeneration = ''
  }

  private inWindow(offset: number) { return offset >= 0 && Math.abs(offset - this.center) <= 100 }
  private prune() { for (const offset of this.pages.keys()) if (!this.inWindow(offset)) this.pages.delete(offset) }
}
