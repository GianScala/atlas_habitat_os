/**
 * Which of the dashboard's two views is on screen.
 *
 * Habitat consumption and Room analysis answer different questions from
 * different meters, so the page shows one at a time and this says which —
 * top right of the control strip, in the same segmented form as the time
 * window below it, because both are "pick exactly one".
 *
 * The unselected segment stays fully legible rather than greying out. It is
 * not disabled; it is the other half of the page, and it should read as
 * somewhere to go.
 */

import { VIEWS, type ViewKey } from '@/lib/views'

interface ViewSwitchProps {
  value: ViewKey
  onChange: (key: ViewKey) => void
}

export function ViewSwitch({ value, onChange }: ViewSwitchProps) {
  return (
    <div className="views" role="group" aria-label="Dashboard view">
      {VIEWS.map((view) => (
        <button
          key={view.key}
          type="button"
          className={view.key === value ? 'view view--on' : 'view'}
          onClick={() => onChange(view.key)}
          aria-pressed={view.key === value}
          title={view.blurb}
        >
          {view.label}
        </button>
      ))}
    </div>
  )
}
