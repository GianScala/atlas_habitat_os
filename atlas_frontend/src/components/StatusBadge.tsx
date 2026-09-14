/**
 * Whether the habitat database is actually reachable.
 *
 * Worth its own indicator: "the app is running" and "the sensors can be read"
 * are different claims, and when the second is false every answer will be an
 * apology. Better to say so up front than to let someone discover it one
 * question at a time.
 *
 * It reports state and nothing else. It used to end with a bare "37
 * measurements", which named a quantity without naming what was counted; the
 * count now lives on the dashboard readout where there is room to say what it
 * means, and in this badge's tooltip.
 */

import { describeMeasurements } from '@/lib/format'
import type { HealthStatus } from '@/lib/types'

interface StatusBadgeProps {
  health: HealthStatus | null
  checking: boolean
  error: string | null
}

/** (modifier, label, tooltip) for the current state. */
function readState(
  health: HealthStatus | null,
  checking: boolean,
  error: string | null,
): [string, string, string | undefined] {
  if (checking) return ['checking', 'Link check', 'Checking the habitat data link…']

  if (error || !health) {
    return ['down', 'Link offline', error ?? 'The ATLAS backend could not be reached.']
  }

  if (health.datasource_ok === false) {
    return [
      'down',
      'No habitat data',
      health.datasource_detail ?? 'The habitat database could not be queried.',
    ]
  }

  // The model is named by its own badge beside this one; what this reports is
  // whether it can actually answer — a local runtime that is not running, or
  // weights that were never downloaded, are both "no answers from here".
  if (!health.model_ready) {
    return [
      'warn',
      'Model offline',
      health.model_detail ?? 'No model is ready, so questions cannot be answered.',
    ]
  }

  const detail =
    health.measurement_count !== null
      ? `Habitat database reachable. ${describeMeasurements(health.measurement_count)}`
      : (health.datasource_detail ?? 'Habitat database reachable.')

  return ['ok', 'Link nominal', detail]
}

export function StatusBadge({ health, checking, error }: StatusBadgeProps) {
  const [modifier, label, detail] = readState(health, checking, error)

  return (
    <span className={`status status--${modifier}`} title={detail} role="status">
      <span className="status__dot" aria-hidden />
      {/* Classed so the narrow layout can drop the words and keep the dot —
          see `status.css`. It stays in the accessibility tree either way. */}
      <span className="status__label">{label}</span>
    </span>
  )
}
