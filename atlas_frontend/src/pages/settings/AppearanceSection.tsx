/**
 * Appearance.
 *
 * All three settings on show at once, as a row you read rather than a button
 * you cycle. The old header toggle named only where you were, so "System" and
 * "Light" looked identical on a light machine and pressing it was the only
 * way to find out which you had.
 *
 * "System" is not a third colour scheme — it is the absence of an override —
 * so the row says what it currently resolves to.
 */

import { THEMES, type Theme } from '@/theme/theme'
import { useTheme } from '@/theme/useTheme'

const LABELS: Record<Theme, string> = {
  system: 'System',
  light: 'Light',
  dark: 'Dark',
}

const BLURBS: Record<Theme, string> = {
  system: 'Follow this machine, and keep following it when it changes at sunset',
  light: 'Always light, whatever the machine is set to',
  dark: 'Always dark, whatever the machine is set to',
}

export function AppearanceSection() {
  const { theme, resolved, setTheme } = useTheme()

  return (
    <section className="settings__section">
      <h2 className="settings__title">Appearance</h2>
      <p className="settings__lede">
        One palette in two settings: paper and ink, swapped.
        Charts, the transcript and the header all follow this.
      </p>

      <div className="settings__choices" role="group" aria-label="Appearance">
        {THEMES.map((option) => (
          <button
            key={option}
            type="button"
            className={option === theme ? 'button button--primary' : 'button'}
            onClick={() => setTheme(option)}
            aria-pressed={option === theme}
            title={BLURBS[option]}
          >
            {/* Not `button__label`: that class disappears below 640px, which
                is fine for a button with an icon and leaves this one blank. */}
            {LABELS[option]}
          </button>
        ))}
      </div>

      <p className="settings__note">
        {theme === 'system'
          ? `Following this machine: ${resolved} right now`
          : `${LABELS[theme]}, regardless of what this machine is set to`}
      </p>
    </section>
  )
}
