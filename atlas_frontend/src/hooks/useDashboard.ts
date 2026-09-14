/**
 * Dashboard data for a time range.
 *
 * One request fetches every panel. That is deliberate: the panels share a
 * window, and ten parallel requests would let them drift a few seconds apart
 * — enough that two charts of the same moment disagree at the right edge.
 *
 * That one request is also the slowest thing the interface does, so its answer
 * is kept in `lib/cache.ts` and survives leaving the page. Coming back draws
 * the charts from the cached payload immediately and, if it has aged past
 * `TTL.dashboard`, refetches behind them — the reader sees the dashboard they
 * left, not "Loading panels…" and an empty page. Each range is cached
 * separately, so flipping between two windows stops re-fetching after the
 * first visit to each.
 *
 * WHICH WINDOW IS ON SCREEN IS PART OF THE ANSWER. Keeping the drawn charts up
 * while a request runs is right when it is the same window being refreshed and
 * wrong when it is not: change the range and, for as long as the request takes,
 * every chart on the page is the OLD window drawn under the NEW window's
 * heading, with nothing saying so. The page looked like it had ignored the
 * click, and a reader who did not wait read figures for the wrong hours.
 *
 * So the payload's own `range` is compared against the range currently
 * selected, and `superseded` says when they disagree. The page keeps drawing
 * the old charts — blanking them loses the reader's place for no gain — but
 * marks them as not being the answer to the question now being asked. What it
 * must never do is present them as if they were.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchDashboard, fetchRanges } from '@/lib/api'
import { CacheKey, isFresh, readCache, TTL, writeCache } from '@/lib/cache'
import type { Dashboard, RangeOption } from '@/lib/types'

interface UseDashboard {
  dashboard: Dashboard | null
  ranges: RangeOption[]
  /** Nothing is drawn yet and a request is running. */
  loading: boolean
  /** Something is drawn and a request is running behind it. */
  refreshing: boolean
  /** What is drawn covers a different window than the one now selected. */
  superseded: boolean
  /** When the drawn payload was read from the habitat, as epoch ms. */
  readAt: number | null
  error: string | null
  refresh: () => void
}

export function useDashboard(range: string): UseDashboard {
  // Seeded rather than assigned in an effect: an effect runs after the first
  // paint, so the page would still flash its loading state for one frame with
  // the answer already in hand.
  const [dashboard, setDashboard] = useState<Dashboard | null>(
    () => readCache<Dashboard>(CacheKey.dashboard(range))?.value ?? null,
  )
  const [readAt, setReadAt] = useState<number | null>(
    () => readCache<Dashboard>(CacheKey.dashboard(range))?.at ?? null,
  )
  const [ranges, setRanges] = useState<RangeOption[]>(
    () => readCache<RangeOption[]>(CacheKey.ranges)?.value ?? [],
  )
  // One flag for "a request is running", from which both of the states the
  // page cares about are derived. Two independent booleans kept drifting out
  // of step with each other and with what was actually on screen.
  const [pending, setPending] = useState(
    () => !isFresh(readCache(CacheKey.dashboard(range)), TTL.dashboard),
  )
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  /** The range the hook is currently working towards. */
  const wantedRef = useRef(range)

  // The presets do not change while the tab is open, so one fetch per session.
  useEffect(() => {
    const cached = readCache<RangeOption[]>(CacheKey.ranges)
    if (cached) return

    const controller = new AbortController()
    fetchRanges(controller.signal)
      .then((options) => {
        writeCache(CacheKey.ranges, options)
        setRanges(options)
      })
      .catch(() => {
        // The picker falls back to its built-in list.
      })
    return () => controller.abort()
  }, [])

  const load = useCallback((key: string, force = false) => {
    abortRef.current?.abort()
    wantedRef.current = key

    // A failure belonged to the window that failed. Carrying it into the next
    // one replaced that window's charts with the previous one's error message
    // for as long as the new request took.
    setError(null)

    const cached = readCache<Dashboard>(CacheKey.dashboard(key))
    if (cached) {
      // Show it now, whether or not a refetch follows.
      setDashboard(cached.value)
      setReadAt(cached.at)
      if (!force && isFresh(cached, TTL.dashboard)) {
        setPending(false)
        return
      }
    }

    const controller = new AbortController()
    abortRef.current = controller
    setPending(true)

    fetchDashboard(key, controller.signal)
      .then((data) => {
        writeCache(CacheKey.dashboard(key), data)
        // An abort is not always instant, and a response that arrives for a
        // window nobody is looking at any more must not land on the page.
        if (wantedRef.current !== key) return
        setDashboard(data)
        setReadAt(Date.now())
        setError(null)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted || wantedRef.current !== key) return
        setError(
          caught instanceof Error ? caught.message : 'Could not load the dashboard.',
        )
      })
      .finally(() => {
        if (controller.signal.aborted || wantedRef.current !== key) return
        setPending(false)
      })
  }, [])

  useEffect(() => {
    load(range)
    return () => abortRef.current?.abort()
  }, [load, range])

  // The button means "get me the current numbers", so it ignores the TTL.
  const refresh = useCallback(() => load(range, true), [load, range])

  return {
    dashboard,
    ranges,
    loading: pending && dashboard === null,
    refreshing: pending && dashboard !== null,
    // The backend echoes the range key it was given, so this compares the
    // window that was actually drawn against the one now selected rather
    // than trusting a flag we set ourselves.
    superseded: dashboard !== null && dashboard.range !== range,
    readAt,
    error,
    refresh,
  }
}
