/**
 * The crew's meter log, and every write to it.
 *
 * Same arrangement as `useMission`, and for the same reason: EVERY WRITE GOES
 * THROUGH HERE and every write replaces the whole payload. That is not
 * tidiness. One reading closes the block before it and opens the block after
 * it, so typing a single number moves two days' consumption, the day totals,
 * every window total, and every share on the page. A hook that patched the one
 * cell it just sent would leave the rest of the page arguing with it.
 *
 * The backend does that arithmetic and returns all of it, so there is no
 * derivation in this file at all — which is what stops the sheet and the charts
 * from ever disagreeing about what was typed.
 *
 * `saving` is a SET of cell keys rather than a boolean. A crew filling in a
 * morning's rounds tabs through eleven boxes faster than eleven round trips
 * come back, and a single flag would either lock the sheet or flicker; a set
 * lets each box report only on itself while the others stay typeable.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { clearLogbook, fetchLogbook, saveReading } from '@/lib/api'
import { CacheKey, dropCache, isFresh, readCache, TTL, writeCache } from '@/lib/cache'
import type { Logbook, ReadingWrite } from '@/lib/types'

/** Which box a write is about — the sheet's own coordinate, in one string. */
export function cellKey(entry: {
  resource: string
  meter: string
  day_index: number
  slot: string
}): string {
  return `${entry.resource}:${entry.meter}:${entry.day_index}:${entry.slot}`
}

export interface UseLogbook {
  logbook: Logbook | null
  loading: boolean
  /** True while refreshing something already drawn, to avoid a flash. */
  refreshing: boolean
  error: string | null
  /** Set by a write the backend refused, cleared by the next attempt. */
  saveError: string | null
  /** The cells with a write in flight, by {@link cellKey}. */
  saving: Set<string>
  refresh: () => void
  /** Store one reading, or withdraw it with a null value. */
  write: (entry: ReadingWrite) => Promise<boolean>
  clear: (resource?: string) => Promise<boolean>
  clearSaveError: () => void
}

export function useLogbook(): UseLogbook {
  const [logbook, setLogbook] = useState<Logbook | null>(
    () => readCache<Logbook>(CacheKey.logbook)?.value ?? null,
  )
  const [loading, setLoading] = useState(
    () => readCache(CacheKey.logbook) === undefined,
  )
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState<Set<string>>(() => new Set())

  const abortRef = useRef<AbortController | null>(null)
  const hasDataRef = useRef(logbook !== null)

  const load = useCallback((force = false) => {
    abortRef.current?.abort()
    setError(null)

    const cached = readCache<Logbook>(CacheKey.logbook)
    if (cached) {
      setLogbook(cached.value)
      hasDataRef.current = true
      setLoading(false)
      if (!force && isFresh(cached, TTL.logbook)) {
        setRefreshing(false)
        return
      }
    }

    const controller = new AbortController()
    abortRef.current = controller

    if (hasDataRef.current) setRefreshing(true)
    else setLoading(true)

    fetchLogbook(controller.signal)
      .then((fresh) => {
        writeCache(CacheKey.logbook, fresh)
        if (controller.signal.aborted) return
        setLogbook(fresh)
        hasDataRef.current = true
        setError(null)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(
          caught instanceof Error ? caught.message : 'Could not load the meter log.',
        )
      })
      .finally(() => {
        if (controller.signal.aborted) return
        setLoading(false)
        setRefreshing(false)
      })
  }, [])

  useEffect(() => {
    load()
    return () => abortRef.current?.abort()
  }, [load])

  /**
   * Apply one write and take its answer as the new truth.
   *
   * Returns whether it was stored, so the box can keep what the crew typed on
   * a refusal instead of silently reverting to the last good reading — which
   * would look exactly like the write having worked.
   */
  const apply = useCallback(
    async (key: string | null, write: () => Promise<Logbook>) => {
      if (key !== null) {
        setSaving((current) => new Set(current).add(key))
      }
      setSaveError(null)
      try {
        const fresh = await write()
        writeCache(CacheKey.logbook, fresh)
        setLogbook(fresh)
        hasDataRef.current = true
        return true
      } catch (caught) {
        setSaveError(
          caught instanceof Error ? caught.message : 'Could not store that reading.',
        )
        return false
      } finally {
        if (key !== null) {
          setSaving((current) => {
            const next = new Set(current)
            next.delete(key)
            return next
          })
        }
      }
    },
    [],
  )

  return {
    logbook,
    loading,
    refreshing,
    error,
    saveError,
    saving,
    refresh: useCallback(() => load(true), [load]),
    write: useCallback(
      (entry: ReadingWrite) => apply(cellKey(entry), () => saveReading(entry)),
      [apply],
    ),
    clear: useCallback(
      (resource?: string) => {
        // The drawn figures came from readings that are about to stop
        // existing. Drop them rather than let a revalidation race the redraw.
        dropCache(CacheKey.logbook)
        return apply(null, () => clearLogbook(resource))
      },
      [apply],
    ),
    clearSaveError: useCallback(() => setSaveError(null), []),
  }
}
