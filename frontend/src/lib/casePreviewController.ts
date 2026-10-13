import type { CaseData, CasePreview } from './backend'
import { requestLane } from './requestLane'

type Job = { key: string; run: () => Promise<void>; discard: () => void }
/** One dispatch lane for previews and selected full data. Running work is never cancelled. */
export class CasePreviewController {
  private epoch = 0
  private revisions = new Map<string, number>()
  private completed = new Map<string, CasePreview>()
  private sizes = new Map<string, number>()
  private bytes = 0
  private pending = new Map<string, Promise<CasePreview | undefined>>()
  private priority = new Set<string>()
  private queue: Job[] = []
  private running = false
  private fetch: <T>(command: string, payload: Record<string, unknown>, options?: {background?:boolean;valid?:()=>boolean;key?:string}) => Promise<T>
  constructor(fetch: <T>(command: string, payload: Record<string, unknown>, options?: {background?:boolean;valid?:()=>boolean;key?:string}) => Promise<T>) { this.fetch = fetch }
  cached(id: string) { const value=this.completed.get(id); if(value) {this.completed.delete(id);this.completed.set(id,value)} return value }
  clear() {
    this.epoch++; this.completed.clear(); this.sizes.clear(); this.bytes=0; this.revisions.clear(); this.pending.clear();this.priority.clear()
    this.queue.splice(0).forEach(job => job.discard())
  }
  invalidate(id: string) {
    this.revisions.set(id, (this.revisions.get(id) ?? 0) + 1)
    this.bytes-=this.sizes.get(id) ?? 0; this.sizes.delete(id); this.completed.delete(id); this.pending.delete(id);this.priority.delete(id)
  }
  reconcile(ids: string[]) {
    this.clear()
    this.prefetch(ids)
  }
  prefetch(ids: string[]) { ids.forEach(id => { void this.preview(id).catch(() => {}) }) }
  private enqueue(job: Job, priority: boolean) {
    if (priority) this.queue.unshift(job); else this.queue.push(job)
    void this.drain()
  }
  private async drain() {
    if (this.running) return
    this.running = true
    try { while (this.queue.length) await this.queue.shift()!.run() }
    finally { this.running = false }
  }
  preview(id: string, priority = false): Promise<CasePreview | undefined> {
    const cached = this.cached(id)
    if (cached) return Promise.resolve(cached)
    if(priority) this.priority.add(id)
    const requestKey=`header:${this.epoch}:${this.revisions.get(id) ?? 0}:${id}`
    const existing = this.pending.get(id)
    if (existing) {
      if (priority) {
        requestLane.promote(requestKey)
        const index = this.queue.findIndex(job => job.key === id)
        if (index >= 0) this.queue.unshift(...this.queue.splice(index, 1))
      }
      return existing
    }
    const epoch = this.epoch, revision = this.revisions.get(id) ?? 0
    const valid = () => epoch === this.epoch && revision === (this.revisions.get(id) ?? 0)
    let resolve!: (value: CasePreview | undefined) => void, reject!: (reason: unknown) => void
    const promise = new Promise<CasePreview | undefined>((yes, no) => { resolve = yes; reject = no })
    this.pending.set(id, promise)
    this.enqueue({ key: id, discard: () => resolve(undefined), run: async () => {
      try {
        if (!valid()) { resolve(undefined); return }
        const value = await this.fetch<CasePreview>('get_case_header', { case_id: id }, {background:!this.priority.has(id),valid,key:requestKey})
        if (valid()) {
          this.bytes-=this.sizes.get(id) ?? 0; this.sizes.delete(id)
          this.completed.delete(id); this.completed.set(id, value)
          const size=JSON.stringify(value).length*2
          if(size>2*1024*1024) this.completed.delete(id)
          else {this.sizes.set(id,size);this.bytes+=size}
          while (this.completed.size > 64 || this.bytes>2*1024*1024) {
            const oldest=this.completed.keys().next().value!
            this.bytes-=this.sizes.get(oldest) ?? 0;this.sizes.delete(oldest);this.completed.delete(oldest)
          }
          resolve(value)
        } else resolve(undefined)
      } catch (error) { if (valid()) reject(error); else resolve(undefined) }
      finally { if (this.pending.get(id) === promise) {this.pending.delete(id);this.priority.delete(id)} }
    } }, priority)
    return promise
  }
  full(id: string, selected: () => boolean): Promise<CaseData | undefined> {
    const epoch = this.epoch, revision = this.revisions.get(id) ?? 0
    const valid = () => selected() && epoch === this.epoch && revision === (this.revisions.get(id) ?? 0)
    return new Promise((resolve, reject) => this.enqueue({ key: `full:${id}`, discard: () => resolve(undefined), run: async () => {
      try {
        if (!valid()) { resolve(undefined); return }
        const data = await this.fetch<CaseData>('get_case_data', { case_id: id })
        resolve(valid() ? data : undefined)
      } catch (error) { if (valid()) reject(error); else resolve(undefined) }
    } }, true))
  }
}

export function afterPaint(work: () => void) {
  if (typeof requestAnimationFrame === 'undefined') { work(); return }
  requestAnimationFrame(() => requestAnimationFrame(work))
}
