/**
 * The three things this dashboard is for, kept apart.
 *
 * Water drawn and mains power are properties of the habitat: there is one
 * clean-water tank and one meter on the wall, and no room owns a share of
 * either. Temperature, humidity, CO₂ and the submetered power draw are
 * properties of a room, and only mean something once you say which room.
 *
 * Shown on one page those two kinds sit side by side under a single room
 * filter, which quietly implies the filter applies to all of them — so
 * narrowing to the dormitory leaves the whole-habitat water chart unchanged
 * and looks like a bug. They are separate views instead, and the switch says
 * which one you are reading.
 *
 * Which view a panel belongs to is a contract with the backend catalogue: a
 * panel whose series are rooms is named `room_*`. See the `PANELS` tuple in
 * `atlas_backend/app/services/dashboard.py` — add a per-room panel there and
 * it lands in Room analysis here with nothing else to change.
 *
 * MISSION PLAN is the third, and it is not made of panels at all. The first
 * two answer "what did the habitat do"; this one answers "and was that what
 * we said we would do", and then "so what does a day cost from here" — both of
 * which need a number no sensor produced. It draws from `/api/mission`,
 * carries its own controls, and shares only the switch — hence `isPanelView`,
 * which is what the panel machinery is gated on.
 */

import type { Panel } from './types'

export type ViewKey = 'habitat' | 'rooms' | 'mission'

export interface ViewOption {
  key: ViewKey
  label: string
  /** What this view shows, said once beside the switch. */
  blurb: string
}

export const VIEWS: readonly ViewOption[] = [
  {
    key: 'habitat',
    label: 'Habitat consumption',
    blurb: 'Water and power for the habitat as a whole — one meter, no room split',
  },
  {
    key: 'rooms',
    label: 'Room analysis',
    blurb: 'Conditions and power draw per room, for the rooms you select',
  },
  {
    key: 'mission',
    label: 'Mission plan',
    blurb: 'Water and power against the mission plan — today, this cycle, the whole mission',
  },
] as const

export const DEFAULT_VIEW: ViewKey = 'habitat'

/** Does this view draw the dashboard's panels, or something of its own? */
export function isPanelView(view: ViewKey): boolean {
  return view !== 'mission'
}

/** Are this panel's series rooms — and so is it a Room analysis panel? */
export function isRoomPanel(panel: Panel): boolean {
  return panel.id.startsWith('room_')
}

export function viewOf(panel: Panel): ViewKey {
  return isRoomPanel(panel) ? 'rooms' : 'habitat'
}

/** A stored value, only if it is still one of the views we offer. */
export function parseView(stored: string | null): ViewKey | null {
  return VIEWS.some((view) => view.key === stored) ? (stored as ViewKey) : null
}
