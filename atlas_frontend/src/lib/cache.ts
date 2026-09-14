/**
 * What the pages have already fetched, kept across route changes.
 *
 * React unmounts a page when you navigate away, and with it every piece of
 * state its hooks were holding. Without somewhere outside the tree to put it,
 * a trip to the dashboard and back re-fetches the conversation list, the open
 * transcript, and the health badge, and a trip the other way re-fetches every
 * panel — each one starting from an empty screen even though the answer was on
 * screen a second ago.
 *
 * So the hooks read from here first and render immediately, then revalidate in
 * the background if the entry has aged past what that particular resource can
 * tolerate. The revalidation is silent: the cached data stays on screen while
 * it runs, which is the difference between "briefly out of date" and "blank".
 *
 * Deliberately a plain module-scoped Map rather than a cache library:
 *
 *   - It lives as long as the tab does and dies with a reload, which is the
 *     right lifetime for telemetry. A hard refresh should mean fresh numbers.
 *   - Nothing subscribes to it. Entries are read when a hook mounts and
 *     written when a fetch lands; no component re-renders because the store
 *     changed, so it cannot become a second, competing source of truth.
 *
 * That second point is the constraint to keep in mind when adding to this: an
 * entry is a starting value for a hook's state, not a live binding to it.
 */

/** A cached value and when it was stored. */
interface Entry<T> {
  value: T
  /** `Date.now()` at the moment it was written. */
  at: number
}

const store = new Map<string, Entry<unknown>>()

/**
 * Where each resource is filed.
 *
 * Central so a typo cannot quietly split one resource into two entries that
 * never hit — the failure mode of caches keyed by inline strings.
 */
export const CacheKey = {
  health: 'health',
  suggestions: 'suggestions',
  conversations: 'conversations',
  conversation: (id: string) => `conversation:${id}`,
  ranges: 'dashboard:ranges',
  dashboard: (range: string) => `dashboard:${range}`,
  tracking: 'mission:tracking',
  logbook: 'mission:logbook',
} as const

/** Everything filed under {@link CacheKey.conversation}. */
const CONVERSATION_PREFIX = 'conversation:'

/**
 * How long an entry may be served before the hook revalidates behind it.
 *
 * These are about how fast the underlying thing actually changes, not about
 * saving requests — the cached value is shown either way, and a revalidation
 * costs nothing the reader can see.
 */
export const TTL = {
  /** Sensor readings bucket at minutes; seconds of drift are invisible. */
  dashboard: 30_000,
  /** A day's allowance moves at the pace of a day. Half a minute is nothing. */
  tracking: 30_000,
  /**
   * The meter log changes only when a person types in it, and this client is
   * the only thing that types. A minute is purely about the other tab, or the
   * other laptop on the same habitat network.
   */
  logbook: 60_000,
  /** Titles and timestamps move whenever a turn finishes. */
  conversations: 15_000,
  /** Matches the health poll, so a route change cannot outpace it. */
  health: 60_000,
  /** Only this client writes transcripts; another tab is the reason to look. */
  conversation: 300_000,
  /** The range presets and starter questions are fixed for the session. */
  static: Number.POSITIVE_INFINITY,
} as const

export function readCache<T>(key: string): Entry<T> | undefined {
  return store.get(key) as Entry<T> | undefined
}

/** The cached value alone, for callers with nothing to decide about its age. */
export function cachedValue<T>(key: string): T | undefined {
  return readCache<T>(key)?.value
}

export function writeCache<T>(key: string, value: T): void {
  store.set(key, { value, at: Date.now() })
}

/**
 * Rewrite an entry in place, if it is there.
 *
 * For local edits that are already known to be true — a deleted thread leaving
 * the list — so the next mount does not briefly show the row again while the
 * revalidation is in flight. A miss is a no-op: there is nothing to correct.
 */
export function updateCache<T>(key: string, change: (current: T) => T): void {
  const entry = readCache<T>(key)
  if (entry) store.set(key, { value: change(entry.value), at: entry.at })
}

export function dropCache(key: string): void {
  store.delete(key)
}

/** Forget every stored transcript, for when the history is cleared. */
export function dropConversationCache(): void {
  for (const key of store.keys()) {
    if (key.startsWith(CONVERSATION_PREFIX)) store.delete(key)
  }
}

/** Is this entry young enough to serve without going back to the backend? */
export function isFresh(entry: Entry<unknown> | undefined, ttlMs: number): boolean {
  return entry !== undefined && Date.now() - entry.at < ttlMs
}
