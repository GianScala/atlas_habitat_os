import { useCallback, useEffect, useMemo, useState } from 'react'

import { DEFAULT_RANGE, FALLBACK_RANGES, isKnownRange } from '@/lib/ranges'
import type { RangeOption } from '@/lib/types'
import { DEFAULT_VIEW, parseView, type ViewKey } from '@/lib/views'

/**
 * The two choices that survive a visit: the window, and the view.
 *
 * Deliberately knows nothing about the payload. The window is what the
 * request is made from, so this has to settle before the fetch — which is why
 * the list of offered windows arrives later, through `useRangeOptions`,
 * rather than being a parameter here.
 */

const RANGE_KEY = 'atlas.dashboard.range'
const VIEW_KEY = 'atlas.dashboard.view'

export function useDashboardPrefs() {
  const [range, setRange] = useState(
    () => window.localStorage.getItem(RANGE_KEY) ?? DEFAULT_RANGE,
  )
  const [view, setView] = useState<ViewKey>(
    () => parseView(window.localStorage.getItem(VIEW_KEY)) ?? DEFAULT_VIEW,
  )

  const changeRange = useCallback((key: string) => {
    window.localStorage.setItem(RANGE_KEY, key)
    setRange(key)
  }, [])

  const changeView = useCallback((key: ViewKey) => {
    window.localStorage.setItem(VIEW_KEY, key)
    setView(key)
  }, [])

  /** Forget a stored window and go back to the default. */
  const resetRange = useCallback(() => {
    window.localStorage.removeItem(RANGE_KEY)
    setRange(DEFAULT_RANGE)
  }, [])

  return { range, changeRange, view, changeView, resetRange }
}

/**
 * The windows on offer, and the repair of a stored one that is not among
 * them.
 *
 * A window remembered from a past visit may no longer be offered — the preset
 * list is version-specific and this one has changed. Fall back to the default
 * rather than open the page on "Unknown range '15m'".
 */
export function useRangeOptions(
  ranges: RangeOption[],
  range: string,
  resetRange: () => void,
): RangeOption[] {
  const options = useMemo(
    () => (ranges.length > 0 ? ranges : FALLBACK_RANGES),
    [ranges],
  )

  useEffect(() => {
    if (isKnownRange(range, options)) return
    resetRange()
  }, [options, range, resetRange])

  return options
}
