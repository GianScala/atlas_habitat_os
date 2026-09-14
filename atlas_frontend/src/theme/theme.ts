/**
 * The theme, and the one place that knows how it is stored and applied.
 *
 * Three settings, not two. "System" is the default and is not the same as
 * light: it means "follow the OS", and it keeps following it when the OS
 * changes at sunset. Choosing light or dark is an override that outlives the
 * tab.
 *
 * How it reaches the CSS: `system` removes the attribute entirely, so
 * `@media (prefers-color-scheme: dark)` in `tokens/theme-dark.css` decides.
 * An override sets `data-theme`, which both dark blocks are written to
 * respect — the media block bows out via `:not([data-theme='light'])`, and
 * `:root[data-theme='dark']` wins in the other direction.
 *
 * Kept as plain functions rather than a context: the only state is one
 * string, and `index.html` has to be able to apply it before React exists.
 */

export type Theme = 'light' | 'dark' | 'system'

export const THEMES: readonly Theme[] = ['system', 'light', 'dark'] as const

/** Shared with the pre-paint script in `index.html`. Change both together. */
export const THEME_STORAGE_KEY = 'atlas.theme'

export function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system'
}

/** The stored override, or `system` when there is none or storage is barred. */
export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(stored) ? stored : 'system'
  } catch {
    // Safari in private mode throws rather than returning null.
    return 'system'
  }
}

/** Write the attribute the stylesheet reads, and remember the choice. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement

  if (theme === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', theme)
  }

  try {
    if (theme === 'system') localStorage.removeItem(THEME_STORAGE_KEY)
    else localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Not being able to remember the choice is not a reason to refuse it.
  }
}

/** What the reader would actually see right now, with `system` resolved. */
export function resolveTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** The next setting in the cycle the toggle walks. */
export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] as Theme
}
