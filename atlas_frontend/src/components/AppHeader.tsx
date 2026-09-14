/**
 * The top bar, shared by every page.
 *
 * Both pages used to build their own header out of the same four elements,
 * which is how the two ended up with different heights and a wordmark that
 * moved when you navigated. One component now owns the identity block, the
 * data-link light, and the rule underneath; each page supplies only the
 * actions that belong to it.
 *
 * The right-hand side is fixed and the same everywhere, because a control
 * that moves between pages has to be found again on each of them:
 *
 *   link light — whether the sensors can be read at all
 *   the other place — Dashboard from the assistant, Assistant from anywhere
 *                     else; there are two rooms, so one button is enough
 *   settings — which model answers and how the app looks
 *
 * The nav button is worked out from the route rather than passed in, so no
 * page can offer a link back to itself.
 */

import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { useLiveTurn } from '@/hooks/useLiveTurn'
import { ChartIcon, ChatIcon, Logo, Settings } from '@/icons'
import type { HealthStatus } from '@/lib/types'

import { StatusBadge } from './StatusBadge'
import { WorkInProgress } from './WorkInProgress'

interface AppHeaderProps {
  /** What this page is, in three or four words. */
  tagline: string
  health: HealthStatus | null
  checking: boolean
  error: string | null
  /** Page-specific buttons, placed between the status light and the nav. */
  children?: ReactNode
}

/** The chat lives at `/` and `/c/:id`; everything else is a leaf page. */
function isChatRoute(pathname: string): boolean {
  return pathname === '/' || pathname.startsWith('/c/')
}

export function AppHeader({
  tagline,
  health,
  checking,
  error,
  children,
}: AppHeaderProps) {
  // Read here rather than passed in: a turn outlives the page that started
  // it, so every page's header must be able to report one it knows nothing
  // about.
  const turn = useLiveTurn()
  const { pathname } = useLocation()

  const toDashboard = isChatRoute(pathname)
  const onSettings = pathname.startsWith('/settings')

  return (
    <header className="header">
      <div className="header__inner bleed__inner">
        <div className="header__identity">
          {/* The mark carries no text, so it sits beside the wordmark rather
              than repeating it. Drawn inline so it takes the theme's colour. */}
          <Logo size={19} className="header__mark" />
          <span className="header__name">ATLAS</span>
          <span className="header__tagline">{tagline}</span>
        </div>

        <div className="header__spacer" />

        <div className="header__actions">
          <WorkInProgress turn={turn} />
          <StatusBadge health={health} checking={checking} error={error} />
          {children}

          {toDashboard ? (
            <Link className="button" to="/dashboard" title="Charts of the live telemetry">
              <ChartIcon />
              <span className="button__label">Dashboard</span>
            </Link>
          ) : (
            <Link className="button" to="/" title="Back to the assistant">
              <ChatIcon />
              <span className="button__label">Assistant</span>
            </Link>
          )}

          <Link
            className="icon-button"
            to="/settings"
            title="Settings"
            aria-label="Settings"
            aria-current={onSettings ? 'page' : undefined}
          >
            <Settings />
          </Link>
        </div>
      </div>
    </header>
  )
}
