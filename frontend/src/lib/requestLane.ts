type Job = { run: () => Promise<unknown>; valid: () => boolean; background: boolean; priority: number; idleNeutral: boolean; key?: string; resolve: (value: unknown) => void; reject: (error: unknown) => void }
export class ObsoleteRequest extends Error {}

/** All IPC shares one lane: queued foreground reads precede speculative work. */
export class RequestLane {
  private jobs: Job[] = []
  private running = false
  private scheduled = false
  private idleReady = false
  private idleTimer?: ReturnType<typeof setTimeout>
  enqueue<T>(run: () => Promise<T>, background = false, valid = () => true, key?: string, priority = 1, idleNeutral = false): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.jobs.push({ run, background, priority, idleNeutral, valid, key, resolve: value => resolve(value as T), reject })
      if (!idleNeutral && (!background || priority < 3)) {
        this.idleReady = false
        if (this.idleTimer) { clearTimeout(this.idleTimer); this.idleTimer = undefined }
      }
      this.schedule()
    })
  }
  promote(key: string) {
    const job = this.jobs.find(job => job.key === key)
    if (!job) return
    job.background = false
    this.idleReady = false
    if (this.idleTimer) { clearTimeout(this.idleTimer); this.idleTimer = undefined }
    this.schedule()
  }
  private schedule() {
    if (this.running || this.scheduled) return
    this.scheduled = true
    queueMicrotask(() => { this.scheduled = false; this.pump() })
  }
  private pump() {
    if (this.running) return
    const foreground = this.jobs.findIndex(job => !job.background)
    const background = this.jobs.reduce((best, job, index) => job.priority < (this.jobs[best]?.priority ?? Infinity) ? index : best, 0)
    const index = foreground < 0 ? background : foreground
    const candidate = this.jobs[index]
    // Give navigation effects and adjacent-page prefetch time to join the lane.
    if (candidate?.background && candidate.priority >= 3 && !this.idleReady) {
      if (!this.idleTimer) this.idleTimer = setTimeout(() => { this.idleTimer = undefined; this.idleReady = true; this.pump() }, 250)
      return
    }
    const job = this.jobs.splice(index, 1)[0]
    if (!job) { this.idleReady = false; return }
    if (!job.valid()) { job.reject(new ObsoleteRequest()); this.schedule(); return }
    if (!job.idleNeutral && (!job.background || job.priority < 3)) this.idleReady = false
    this.running = true
    void job.run().then(job.resolve, job.reject).finally(() => { this.running = false; this.schedule() })
  }
}
export const requestLane = new RequestLane()
