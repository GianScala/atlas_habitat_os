/**
 * Turning a payload into something a chart can draw.
 *
 * Pure functions, deliberately: this is the part of the dashboard with real
 * rules in it — which panels belong to the open view, how the room filter
 * applies to the ones it governs, and which series share a colour — and none
 * of it needs React to be true. Keeping it out of the component is what makes
 * it readable on its own, and testable without rendering a page.
 */

import { assignStyles, type SeriesStyle } from '@/lib/palette'
import { describeSeries, type RoomIndex } from '@/lib/rooms'
import type { Panel } from '@/lib/types'
import { viewOf, type ViewKey } from '@/lib/views'

/** A panel plus the two lookups its chart needs. */
export interface Drawable {
  panel: Panel
  colours: Map<string, string>
  dashes: Map<string, string>
  /** The room filter, not the database, is why this panel has nothing on it. */
  filteredOut: boolean
}

/** One heading and the panels under it. */
export interface DrawableGroup {
  name: string
  items: Drawable[]
}

/**
 * Keep this view's panels, apply the room filter to the ones it governs, then
 * hand each panel everything it needs to draw itself: series named as the
 * selector names them, a colour per series, and a stroke wherever more than
 * one series is drawn in that colour.
 *
 * `selectedRooms` of `null` means "not decided yet" and shows everything —
 * distinct from an empty set, which is the reader having cleared the filter.
 */
export function buildDrawables(
  panels: Panel[],
  view: ViewKey,
  index: RoomIndex,
  styles: Map<string, SeriesStyle>,
  selectedRooms: Set<string> | null,
): Drawable[] {
  return panels
    .filter((panel) => viewOf(panel) === view)
    .map((panel) =>
      index.perRoomPanels.has(panel.id)
        ? drawRoomPanel(panel, index, styles, selectedRooms)
        : drawHabitatPanel(panel),
    )
}

/**
 * A habitat panel's series are phases or tanks, not rooms, so they are styled
 * within the panel rather than from the room index — and no room filter
 * applies to them.
 */
function drawHabitatPanel(panel: Panel): Drawable {
  const own = assignStyles(panel.series.map((entry) => entry.key))
  const colours = new Map<string, string>()
  const dashes = new Map<string, string>()

  for (const [key, style] of own) {
    colours.set(key, style.colour)
    if (style.dash) dashes.set(key, style.dash)
  }

  return { panel, colours, dashes, filteredOut: false }
}

function drawRoomPanel(
  panel: Panel,
  index: RoomIndex,
  styles: Map<string, SeriesStyle>,
  selectedRooms: Set<string> | null,
): Drawable {
  const kept = panel.series.filter(
    (entry) =>
      !selectedRooms || selectedRooms.has(index.roomOf.get(entry.key) ?? entry.key),
  )
  const { series, dashes } = describeSeries(kept, index, styles)

  // Every tag reporting a room resolves to that one room's colour.
  const colours = new Map<string, string>()
  for (const entry of series) {
    const style = styles.get(index.roomOf.get(entry.key) ?? entry.key)
    if (style) colours.set(entry.key, style.colour)
  }

  return {
    panel: { ...panel, series },
    colours,
    dashes,
    filteredOut: panel.series.length > 0 && series.length === 0,
  }
}

/** Panels arrive grouped; keep that order rather than sorting alphabetically. */
export function groupDrawables(drawable: Drawable[]): DrawableGroup[] {
  const ordered: DrawableGroup[] = []

  for (const item of drawable) {
    const existing = ordered.find((group) => group.name === item.panel.group)
    if (existing) existing.items.push(item)
    else ordered.push({ name: item.panel.group, items: [item] })
  }

  return ordered
}
