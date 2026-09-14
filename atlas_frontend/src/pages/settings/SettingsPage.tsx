/**
 * Settings, in three sections.
 *
 * They are settings about different things, and a crew arrives wanting one or
 * the other:
 *
 *   AI & models            how ATLAS answers: which model and register.
 *   Database nomenclature  the names shown for the rooms and datasets found in
 *                          the database, and the crew's hand-read dials.
 *   Connectors             documents the assistant may read, indexed locally.
 *
 * The switch is at the top rather than in a sidebar, in the same segmented form
 * the dashboard uses for its views, because it is the same kind of choice: pick
 * exactly one, and the other half should read as somewhere to go rather than as
 * something disabled.
 *
 * Which half is open lives in the URL (`/settings/ai_models`,
 * `/settings/database_nomenclature`) rather than in component state, so a tab
 * can be linked to, bookmarked, and reloaded into. This file is the arrangement
 * and nothing else — each half owns its own data and its own failures.
 */

import { Navigate, useNavigate, useParams } from 'react-router-dom'

import { AppHeader } from '@/components/AppHeader'
import { useHealth } from '@/hooks/useHealth'

import { AiModelsSection } from './AiModelsSection'
import { ConnectorsSection } from './ConnectorsSection'
import { DatabaseNomenclatureSection } from './DatabaseNomenclatureSection'
import {
  DEFAULT_SETTINGS_TAB,
  parseSettingsTab,
  SETTINGS_TABS,
  type SettingsTabKey,
} from './tabs'

export default function SettingsPage() {
  const { tab } = useParams<{ tab: string }>()
  const navigate = useNavigate()
  const { health, checking, error: healthError } = useHealth()

  const active = parseSettingsTab(tab)

  // An address that is not one of the sections is a stale bookmark, not an
  // error worth a page. The first section is the right place to land.
  if (active === null) {
    return <Navigate to={`/settings/${DEFAULT_SETTINGS_TAB}`} replace />
  }

  const change = (key: SettingsTabKey) => navigate(`/settings/${key}`)
  const current = SETTINGS_TABS.find((entry) => entry.key === active)

  return (
    <div className="app">
      {/* Nothing page-specific in the header: what this page changes, it
          changes in its own body, where the thing being changed is. */}
      <AppHeader
        tagline="settings"
        health={health}
        checking={checking}
        error={healthError}
      />

      <div className="settings">
        <div className="settings__inner bleed__inner">
          <div className="settings__switch">
            <div className="views" role="group" aria-label="Settings section">
              {SETTINGS_TABS.map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  className={entry.key === active ? 'view view--on' : 'view'}
                  onClick={() => change(entry.key)}
                  aria-pressed={entry.key === active}
                  title={entry.blurb}
                >
                  {entry.label}
                </button>
              ))}
            </div>
            {current && <p className="settings__switch-blurb">{current.blurb}</p>}
          </div>

          {active === 'ai_models' && <AiModelsSection />}
          {active === 'database_nomenclature' && <DatabaseNomenclatureSection />}
          {active === 'connectors' && <ConnectorsSection />}
        </div>
      </div>
    </div>
  )
}
