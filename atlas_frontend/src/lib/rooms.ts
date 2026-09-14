/**
 * One entry per room, not one entry per tag.
 *
 * The habitat database names the same physical place differently depending on
 * which system is writing. Temperature calls the dormitory `Container3`;
 * Energy calls it `Dormitory`. The backend already folds those together into
 * a single room name — that identity is what lets a room keep one colour
 * across every chart.
 *
 * What it cannot fold is a place reported under two spellings of the SAME
 * name. `AirLock` and `Airlock` are separate tag values in InfluxDB holding
 * separate readings, so the backend deliberately keeps both series rather
 * than averaging two sensor groups nobody asked to combine — and hands them
 * over labelled with their raw tags. Read literally that produced two
 * near-identical rows in the room selector, which looks like a bug in the
 * interface rather than a fact about the data.
 *
 * So the index groups by room name, case-folded: one row, one colour, one
 * entry in the count. Nothing is merged on the plot — where a panel really
 * does carry two series for one room, they share that room's colour and the
 * second is dashed and numbered.
 */

import { strokeFor, type SeriesStyle } from './palette'
import type { Panel, PanelSeries } from './types'
import { isRoomPanel } from './views'

export interface Room {
  /** Case-folded room name — stable across tag spellings. */
  id: string
  /** Display name, taken from the spelling the data uses most. */
  label: string
  /** Every series key reporting this room, anywhere on the dashboard. */
  keys: string[]
}

export interface RoomIndex {
  rooms: Room[]
  /** Series key -> room id. Drives both filtering and colour. */
  roomOf: Map<string, string>
  /** Room id -> display name. */
  nameOf: Map<string, string>
  /**
   * Ids of the panels whose series are rooms.
   *
   * Read off the panel's identity rather than counted from its series: a
   * panel that came back with one room on it is still a per-room panel, and
   * so is one the reader has narrowed to a single room. Counting would strip
   * a chart of its room colours at exactly the moment they matter most.
   */
  perRoomPanels: Set<string>
}

export function buildRoomIndex(panels: Panel[]): RoomIndex {
  // Label spellings seen per room, with how often — the most common one wins
  // the row, so a single oddly-cased tag cannot rename the room.
  const spellings = new Map<string, Map<string, number>>()
  const keys = new Map<string, Set<string>>()
  const perRoomPanels = new Set<string>()

  for (const panel of panels) {
    if (!isRoomPanel(panel)) continue
    perRoomPanels.add(panel.id)

    for (const entry of panel.series) {
      const label = entry.label.trim()
      const id = label.toLocaleLowerCase()
      if (!id) continue

      const counts = spellings.get(id) ?? new Map<string, number>()
      counts.set(label, (counts.get(label) ?? 0) + 1)
      spellings.set(id, counts)

      const group = keys.get(id) ?? new Set<string>()
      group.add(entry.key)
      keys.set(id, group)
    }
  }

  const rooms: Room[] = [...spellings.entries()]
    .map(([id, counts]) => ({
      id,
      label: [...counts.entries()].sort(
        (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
      )[0]![0],
      keys: [...(keys.get(id) ?? [])].sort((a, b) => a.localeCompare(b)),
    }))
    .sort((a, b) => a.label.localeCompare(b.label))

  const roomOf = new Map<string, string>()
  const nameOf = new Map<string, string>()

  for (const room of rooms) {
    nameOf.set(room.id, room.label)
    for (const key of room.keys) roomOf.set(key, room.id)
  }

  return { rooms, roomOf, nameOf, perRoomPanels }
}

/**
 * Name and mark one panel's series.
 *
 * Numbering is decided per panel, never once across the dashboard. The tag
 * `AirLock` means "the second of two airlock sensor groups" on the
 * temperature panel, where both spellings report — and means "the airlock"
 * on the humidity panel, where only one does. Numbering globally would label
 * humidity's only airlock line "AIRLOCK 2" and draw it dashed, announcing a
 * second series that panel does not have.
 *
 * The stroke comes from the room's assigned style rather than from a list
 * starting at solid, because a room past the eighth is already dashed to
 * separate it from the room it shares a colour with. Its second sensor group
 * has to step on from there — see `strokeFor`.
 */
export function describeSeries(
  series: PanelSeries[],
  index: RoomIndex,
  styles: Map<string, SeriesStyle>,
): { series: PanelSeries[]; dashes: Map<string, string> } {
  const byRoom = new Map<string, PanelSeries[]>()
  for (const entry of series) {
    const id = index.roomOf.get(entry.key) ?? entry.key
    byRoom.set(id, [...(byRoom.get(id) ?? []), entry])
  }

  const dashes = new Map<string, string>()
  const named: PanelSeries[] = []

  for (const [id, group] of byRoom) {
    const name = index.nameOf.get(id) ?? group[0]!.label
    const numbered = group.length > 1
    const style = styles.get(id)

    ;[...group]
      .sort((a, b) => a.key.localeCompare(b.key))
      .forEach((entry, position) => {
        const dash = style ? strokeFor(style, position) : ''
        if (dash) dashes.set(entry.key, dash)
        named.push({ ...entry, label: numbered ? `${name} ${position + 1}` : name })
      })
  }

  // Sorted on the name the reader actually sees. The server sorted on the raw
  // tags, which puts `Airlock` before `AirLock` and so listed "AIRLOCK 2"
  // above "AIRLOCK 1".
  named.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }))

  return { series: named, dashes }
}
