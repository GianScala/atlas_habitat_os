/**
 * The mission plan, and consumption measured against it.
 *
 * One hook for both because they are never useful apart: a plan with no usage
 * beside it is a wish, and usage with no plan is the dashboard we already have.
 * The tracking payload carries the plan's figures anyway, so the two arrive
 * together and cannot disagree about what today's allowance is.
 *
 * EVERY WRITE GOES THROUGH HERE, not through the editor, and every write
 * refetches the tracking. That is not tidiness — booking an extra or moving a
 * ceiling re-derives the allowance of every remaining day, so a page still
 * showing 80% of the allowance from two seconds ago would be wrong in the most
 * quietly convincing way available.
 *
 * The cached payload survives leaving the page, on the same terms as the
 * dashboard's: shown at once, revalidated behind it if it has aged past
 * `TTL.tracking`.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  addExtra,
  deleteExtra,
  fetchMissionPlan,
  fetchTracking,
  resetMissionPlan,
  saveExtra,
  saveMissionPlan,
} from '@/lib/api'
import { CacheKey, dropCache, isFresh, readCache, TTL, writeCache } from '@/lib/cache'
import type { ExtraWrite, MissionPlan, PlanUpdate, Tracking } from '@/lib/types'

export interface UseMission {
  tracking: Tracking | null
  plan: MissionPlan | null
  loading: boolean
  /** True while refreshing something already drawn, to avoid a flash. */
  refreshing: boolean
  error: string | null
  /** Set by a write that was refused, and cleared by the next attempt. */
  saveError: string | null
  saving: boolean
  refresh: () => void
  save: (change: PlanUpdate) => Promise<boolean>
  reset: () => Promise<boolean>
  createExtra: (extra: ExtraWrite) => Promise<boolean>
  editExtra: (id: string, extra: ExtraWrite) => Promise<boolean>
  removeExtra: (id: string) => Promise<boolean>
  clearSaveError: () => void
}

export function useMission(): UseMission {
  const [tracking, setTracking] = useState<Tracking | null>(
    () => readCache<Tracking>(CacheKey.tracking)?.value ?? null,
  )
  const [plan, setPlan] = useState<MissionPlan | null>(null)
  const [loading, setLoading] = useState(
    () => readCache(CacheKey.tracking) === undefined,
  )
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const hasDataRef = useRef(tracking !== null)

  const load = useCallback((force = false) => {
    abortRef.current?.abort()
    setError(null)

    const cached = readCache<Tracking>(CacheKey.tracking)
    if (cached) {
      setTracking(cached.value)
      hasDataRef.current = true
      setLoading(false)
      if (!force && isFresh(cached, TTL.tracking)) {
        setRefreshing(false)
        return
      }
    }

    const controller = new AbortController()
    abortRef.current = controller

    if (hasDataRef.current) setRefreshing(true)
    else setLoading(true)

    // The plan comes along for the editor, which needs the fields the tracking
    // payload has no reason to carry — the day boundary, and the ceilings the
    // setup form offers before anything is stored.
    Promise.all([fetchTracking(controller.signal), fetchMissionPlan(controller.signal)])
      .then(([live, stored]) => {
        writeCache(CacheKey.tracking, live)
        if (controller.signal.aborted) return
        setTracking(live)
        setPlan(stored)
        hasDataRef.current = true
        setError(null)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(
          caught instanceof Error ? caught.message : 'Could not load the mission plan.',
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

  const refresh = useCallback(() => load(true), [load])

  /**
   * Store a change and re-derive the plan from it.
   *
   * Returns whether it was stored, so a form can stay open on a refusal with
   * what the crew typed still in it. The backend validates the whole body
   * before writing any of it, so a rejected write leaves the stored plan
   * exactly as it was and there is nothing to roll back here.
   */
  const apply = useCallback(
    async (write: () => Promise<MissionPlan>) => {
      setSaving(true)
      setSaveError(null)
      try {
        setPlan(await write())
        // The drawn figures were derived from the old plan. Drop them rather
        // than let the revalidation race the redraw.
        dropCache(CacheKey.tracking)
        load(true)
        return true
      } catch (caught) {
        setSaveError(
          caught instanceof Error ? caught.message : 'Could not save the plan.',
        )
        return false
      } finally {
        setSaving(false)
      }
    },
    [load],
  )

  return {
    tracking,
    plan,
    loading,
    refreshing,
    error,
    saveError,
    saving,
    refresh,
    save: useCallback((change: PlanUpdate) => apply(() => saveMissionPlan(change)), [apply]),
    reset: useCallback(() => apply(() => resetMissionPlan()), [apply]),
    createExtra: useCallback((extra: ExtraWrite) => apply(() => addExtra(extra)), [apply]),
    editExtra: useCallback(
      (id: string, extra: ExtraWrite) => apply(() => saveExtra(id, extra)),
      [apply],
    ),
    removeExtra: useCallback((id: string) => apply(() => deleteExtra(id)), [apply]),
    clearSaveError: useCallback(() => setSaveError(null), []),
  }
}
