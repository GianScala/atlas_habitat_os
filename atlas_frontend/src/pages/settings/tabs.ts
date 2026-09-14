/**
 * The two halves of Settings, and the addresses they live at.
 *
 * They are separated because they are settings about different things, and a
 * crew arrives wanting one or the other:
 *
 *   ai_models              how ATLAS answers: which model, in what register,
 *                          and what the app looks like while it does.
 *   database_nomenclature  the names shown for the rooms and datasets found in
 *                          the database, and the dials the crew reads by hand.
 *   connectors             documents the assistant may read, indexed locally.
 *
 * Each is a route rather than component state, so a tab can be linked to,
 * bookmarked, and reloaded into.
 */

export type SettingsTabKey = 'ai_models' | 'database_nomenclature' | 'connectors'

export interface SettingsTab {
  key: SettingsTabKey
  label: string
  /** What this half is for, said once beside the switch. */
  blurb: string
}

export const SETTINGS_TABS: readonly SettingsTab[] = [
  {
    key: 'ai_models',
    label: 'AI & models',
    blurb: 'Which model answers, in what register, and how the app looks',
  },
  {
    key: 'database_nomenclature',
    label: 'Database nomenclature',
    blurb: 'Rename the rooms and datasets found in your database',
  },
  {
    key: 'connectors',
    label: 'Connectors',
    blurb: 'Documents the assistant can read: procedures, contacts, checklists',
  },
] as const

export const DEFAULT_SETTINGS_TAB: SettingsTabKey = 'ai_models'

/** A URL segment, only if it is one of the tabs we offer. */
export function parseSettingsTab(value: string | undefined): SettingsTabKey | null {
  return SETTINGS_TABS.some((tab) => tab.key === value)
    ? (value as SettingsTabKey)
    : null
}
