type Job = { run: () => Promise<unknown>; valid: () => boolean; background: boolean; key?: string; resolve: (value: unknown) => void; reject: (error: unknown) => void }
export class ObsoleteRequest extends Error {}

/** All IPC shares one lane: queued foreground reads precede speculative work. */
export class RequestLane {
  private jobs: Job[] = []
  private running = false
  private scheduled = false
  enqueue<T>(run: () => Promise<T>, background = false, valid = () => true, key?: string): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.jobs.push({ run, background, valid, key, resolve: value => resolve(value as T), reject })
      this.schedule()
    })
  }
  promote(key: string) { const job = this.jobs.find(job => job.key === key); if (job) job.background = false }
  private schedule() {
    if (this.running || this.scheduled) return
    this.scheduled = true
    queueMicrotask(() => { this.scheduled = false; this.pump() })
  }
  private pump() {
    if (this.running) return
    const foreground = this.jobs.findIndex(job => !job.background)
    const job = this.jobs.splice(foreground < 0 ? 0 : foreground, 1)[0]
    if (!job) return
    if (!job.valid()) { job.reject(new ObsoleteRequest()); this.schedule(); return }
    this.running = true
    void job.run().then(job.resolve, job.reject).finally(() => { this.running = false; this.schedule() })
  }
}
export const requestLane = new RequestLane()
