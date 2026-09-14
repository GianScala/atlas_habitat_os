import { useCallback, useEffect, useMemo, useState } from 'react'

import { assignStyles } from '@/lib/palette'
import { buildRoomIndex } from '@/lib/rooms'
import type { Panel } from '@/lib/types'

/**
 * Which rooms are drawn, and the colour each one keeps.
 *
 * Derived from the payload rather than from the view, so this runs after the
 * fetch — see `useDashboardPrefs` for the choices that have to run before it.
 */

const ROOMS_KEY = 'atlas.dashboard.rooms'

/** The rooms chosen on a past visit, or null if there was no past visit. */
function readStoredRooms(): string[] | null {
  const raw = window.localStorage.getItem(ROOMS_KEY)
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === 'string')
      : null
  } catch {
    return null
  }
}

export function useRoomSelection(panels: Panel[] | undefined) {
  const [selected, setSelected] = useState<Set<string> | null>(null)

  // Every room on any per-room panel, folded so one place is one room even
  // when the database spells its tag two ways. Built from the whole payload
  // rather than from the current view, so a room's colour cannot depend on
  // which view happened to be open when the page loaded.
  const index = useMemo(() => buildRoomIndex(panels ?? []), [panels])

  // Styles are keyed to the room, not to its position in a filtered list.
  const styles = useMemo(
    () => assignStyles(index.rooms.map((room) => room.id)),
    [index],
  )

  // First load shows every room — the honest default for a view called Room
  // analysis, which the reader then narrows. A choice made on a past visit
  // takes over, minus any room that has since stopped reporting.
  useEffect(() => {
    if (selected !== null || index.rooms.length === 0) return
    const available = index.rooms.map((room) => room.id)
    const stored = readStoredRooms()
    setSelected(
      new Set(stored ? stored.filter((id) => available.includes(id)) : available),
    )
  }, [index, selected])

  useEffect(() => {
    if (selected === null) return
    window.localStorage.setItem(ROOMS_KEY, JSON.stringify([...selected]))
  }, [selected])

  // No cap. Every room can be on at once; past the eighth the palette starts
  // a second lap and those rooms are drawn dashed, so no two rooms are ever
  // the same mark. See `lib/palette.ts`.
  const toggle = useCallback((id: string) => {
    setSelected((current) => {
      const next = new Set(current ?? [])
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const selectAll = useCallback(() => {
    setSelected(new Set(index.rooms.map((room) => room.id)))
  }, [index])

  const clear = useCallback(() => setSelected(new Set()), [])

  return { index, styles, selected, toggle, selectAll, clear }
}
