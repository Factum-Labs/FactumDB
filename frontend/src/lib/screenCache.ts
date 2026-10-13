/** Session-only LRU. No evidence is persisted in browser storage. */
export class ScreenCache {
  private values = new Map<string, { value: unknown; bytes: number; at: number }>()
  private pending = new Map<string, Promise<unknown>>()
  private epoch = 0
  private bytes = 0
  private budget: number
  private maximum: number
  constructor(budget = 12 * 1024 * 1024, maximum = 96) { this.budget = budget; this.maximum = maximum }
  clear() { this.epoch++; this.values.clear(); this.pending.clear(); this.bytes = 0 }
  peek<T>(key: string): T | undefined {
    const entry = this.values.get(key)
    if (!entry) return undefined
    this.values.delete(key); this.values.set(key, entry)
    return entry.value as T
  }
  fresh(key: string) { return Date.now() - (this.values.get(key)?.at ?? 0) < 30_000 }
  load<T>(key: string, fetch: () => Promise<T>): Promise<T> {
    const existing = this.pending.get(key)
    if (existing) return existing as Promise<T>
    const epoch = this.epoch
    const promise = fetch().then(value => {
      if (epoch === this.epoch) {
        const bytes = JSON.stringify(value).length * 2
        const previous = this.values.get(key)
        if (previous) { this.bytes -= previous.bytes; this.values.delete(key) }
        if (bytes <= this.budget) {
          this.values.set(key, { value, bytes, at: Date.now() }); this.bytes += bytes
          while (this.bytes > this.budget || this.values.size > this.maximum) {
            const oldest = this.values.keys().next().value!
            this.bytes -= this.values.get(oldest)!.bytes; this.values.delete(oldest)
          }
        }
      }
      return value
    }).finally(() => { if (this.pending.get(key) === promise) this.pending.delete(key) })
    this.pending.set(key, promise)
    return promise
  }
  size() { return { entries: this.values.size, bytes: this.bytes } }
}
