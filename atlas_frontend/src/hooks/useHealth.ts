/**
 * Backend and datasource health, polled gently.
 *
 * The first check hits `/health/datasource`, which runs a real query — that is
 * the only way to know the sensors are readable rather than merely configured.
 *
 * Both pages show the badge, so the last answer is cached and a route change
 * picks it up where it was. Without that, every navigation ran a live database
 * query and blinked the badge back to "checking" on the way — motion in the
 * header that reported nothing, since nothing had actually changed.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchDatasourceHealth } from '@/lib/api'
import { CacheKey, dropCache, isFresh, readCache, TTL, writeCache } from '@/lib/cache'
import type { HealthStatus } from '@/lib/types'

const POLL_INTERVAL_MS = 60_000

interface UseHealth {
  health: HealthStatus | null
  checking: boolean
  error: string | null
  refresh: () => void
}

export function useHealth(): UseHealth {
  const [health, setHealth] = useState<HealthStatus | null>(
    () => readCache<HealthStatus>(CacheKey.health)?.value ?? null,
  )
  const [checking, setChecking] = useState(
    () => readCache(CacheKey.health) === undefined,
  )
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const check = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const status = await fetchDatasourceHealth(controller.signal)
      writeCache(CacheKey.health, status)
      setHealth(status)
      setError(null)
    } catch (caught) {
      if (controller.signal.aborted) return
      // Forget the last good answer too. A cached "connected" outliving the
      // connection is worse than no badge at all.
      dropCache(CacheKey.health)
      setHealth(null)
      setError(caught instanceof Error ? caught.message : 'Could not reach the backend.')
    } finally {
      if (!controller.signal.aborted) setChecking(false)
    }
  }, [])

  useEffect(() => {
    // A cached status younger than the poll interval is one this hook would
    // have been serving anyway had the page never unmounted.
    if (!isFresh(readCache(CacheKey.health), TTL.health)) void check()
    const timer = window.setInterval(() => void check(), POLL_INTERVAL_MS)
    return () => {
      window.clearInterval(timer)
      abortRef.current?.abort()
    }
  }, [check])

  const refresh = useCallback(() => {
    setChecking(true)
    void check()
  }, [check])

  return { health, checking, error, refresh }
}
