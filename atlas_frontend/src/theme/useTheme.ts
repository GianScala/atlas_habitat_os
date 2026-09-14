import { useCallback, useEffect, useState } from 'react'

import { applyTheme, readTheme, resolveTheme, type Theme } from './theme'

/**
 * The current theme setting, and a way to change it.
 *
 * `resolved` is what is actually on screen — the setting with `system` worked
 * out — which is what a label or an icon wants to show. It re-renders when
 * the OS flips while the setting is `system`, so a toggle sitting in the
 * header does not go stale at sunset.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readTheme)
  const [resolved, setResolved] = useState<'light' | 'dark'>(() => resolveTheme(readTheme()))

  const setTheme = useCallback((next: Theme) => {
    applyTheme(next)
    setThemeState(next)
    setResolved(resolveTheme(next))
  }, [])

  // The attribute is already correct on first paint — `index.html` sets it
  // before the stylesheet lands. This re-applies it only so a React remount
  // cannot leave the DOM disagreeing with the state we just read.
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  // Only `system` cares what the OS is doing; an override does not.
  useEffect(() => {
    if (theme !== 'system') return

    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setResolved(query.matches ? 'dark' : 'light')

    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [theme])

  return { theme, resolved, setTheme }
}
