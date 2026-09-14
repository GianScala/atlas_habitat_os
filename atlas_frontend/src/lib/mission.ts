/**
 * Reading a plan out loud.
 *
 * "80%" is not a verdict. At breakfast it is alarming and at midnight it is a
 * good day, and the difference is how much of the window has passed — which is
 * why every helper here takes the elapsed share as well as the spent one. The
 * backend already decided the status from exactly those two figures; this file
 * only puts words and marks on its decision, and never re-derives it.
 *
 * The one figure this page is really for is the REVISED allowance: what a day
 * may cost from here if the mission is still to close inside its ceiling. It
 * is the only number on the page a crew can act on, so it gets said plainly
 * and never buried in a tooltip.
 *
 * A figure that came from the shipped defaults rather than from the crew is
 * labelled wherever it appears. A default is a starting point for an argument,
 * and one that looks like a decision has stopped being honest.
 */

import type {
  Budget,
  BudgetStatus,
  DayStatus,
  ExtraEntry,
  MissionWindow,
  PlannedDay,
  ResourceTracking,
} from './types'

/** What the status light means, in the fewest words that still say it. */
export const STATUS_LABEL: Record<BudgetStatus, string> = {
  nominal: 'On plan',
  caution: 'Running hot',
  over: 'Over plan',
  unset: 'No ceiling',
  no_data: 'No readings',
}

/** The three instrument colours, and the two states that get neither. */
export const STATUS_TONE: Record<BudgetStatus, Tone> = {
  nominal: 'ok',
  caution: 'warn',
  over: 'bad',
  unset: 'mute',
  no_data: 'mute',
}

export type Tone = 'ok' | 'warn' | 'bad' | 'mute'

/** One mission day's verdict, and the colour it is drawn in. */
export const DAY_TONE: Record<DayStatus, Tone> = {
  over: 'bad',
  under: 'ok',
  on_plan: 'ok',
  no_data: 'mute',
  pending: 'mute',
}

export const DAY_LABEL: Record<DayStatus, string> = {
  over: 'Over',
  under: 'Under',
  on_plan: 'On plan',
  no_data: 'No readings',
  pending: 'Not yet',
}

/** `0.8` -> `80%`. Whole numbers: an allowance is not read to two decimals. */
export function percent(fraction: number | null): string {
  if (fraction === null || !Number.isFinite(fraction)) return '—'
  return `${Math.round(fraction * 100)}%`
}

/**
 * An amount with its unit, or an em dash where there is no amount.
 *
 * Precision follows size for the same reason the charts' does: a column of
 * figures has to line up, and 1142.0978 L is four digits of false confidence
 * on a gauge that resolves to the litre.
 */
export function amount(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const size = Math.abs(value)
  const text =
    size >= 100
      ? Math.round(value).toLocaleString()
      : size >= 10
        ? value.toFixed(1)
        : value.toFixed(2)
  return unit ? `${text} ${unit}` : text
}

/**
 * The sentence at the top of a window card.
 *
 * Both figures, always, in one line — because either alone is the half of the
 * story that misleads. The comparison is against what the plan expected BY NOW
 * rather than against the whole window's allowance, since that is the figure
 * the crew is actually behind or ahead of at this moment.
 */
export function headline(budget: Budget, unit: string): string {
  if (budget.status === 'no_data') {
    return 'Nothing was recorded for this window.'
  }
  if (budget.target === null) {
    return `${amount(budget.used, unit)} used. No ceiling set for this resource.`
  }
  if (budget.planned_by_now === null) {
    return `${amount(budget.used, unit)} of ${amount(budget.target, unit)} planned.`
  }
  return (
    `${amount(budget.used, unit)} used against the ` +
    `${amount(budget.planned_by_now, unit)} the plan expected by now.`
  )
}

/**
 * What the pace means, said as a consequence rather than as a ratio.
 *
 * A projection is only offered where the backend published one; early in a
 * window there is no rate worth reading and the card says that instead.
 */
export function paceReading(budget: Budget, unit: string): string | null {
  if (budget.status === 'over') {
    const past = budget.remaining === null ? null : -budget.remaining
    return `${amount(past, unit)} past the plan, with ${percent(
      1 - budget.elapsed_fraction,
    )} of the window still to go.`
  }
  if (budget.projected === null || budget.target === null) return null

  const verb = budget.projected > budget.target ? 'over' : 'inside'
  const gap = Math.abs(budget.projected - budget.target)
  return (
    `At this rate the window ends at ${amount(budget.projected, unit)} — ` +
    `${amount(gap, unit)} ${verb} the plan.`
  )
}

/** Is this resource's ceiling one the crew has not confirmed? */
export function isDefault(resource: { total: number | null; source: string }): boolean {
  return resource.total !== null && resource.source === 'default'
}

/**
 * Where a meter's fill and its plan mark sit, as fractions of the track.
 *
 * Both are clamped: an allowance spent twice over still fills the bar once, and
 * the overspend is stated in words beside it rather than drawn off the end
 * where nothing can be read from it.
 */
export function meterGeometry(budget: Budget): { fill: number; pace: number } {
  const spent = budget.used_fraction ?? 0
  const planned =
    budget.target && budget.planned_by_now !== null
      ? budget.planned_by_now / budget.target
      : budget.elapsed_fraction
  return {
    fill: clamp(spent),
    pace: clamp(planned),
  }
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/** The unit to print, or nothing at all where the database records none. */
export function unitOf(resource: ResourceTracking): string {
  return resource.unit_source === 'known' ? resource.unit : ''
}

/**
 * How the forward plan changed what a day costs, in one sentence.
 *
 * The comparison, not just the number: "112 a day from here" means nothing
 * without "you planned 128", and the direction is the whole message.
 */
export function forwardReading(resource: ResourceTracking, unit: string): string | null {
  const { flat_per_day: flat, revised_per_day: revised } = resource
  if (flat === null || revised === null) return null

  if (!resource.feasible) {
    return (
      `The extras still booked cost ${amount(resource.shortfall, unit)} more ` +
      `than the ${amount(resource.remaining, unit)} left. No daily figure ` +
      'closes this mission as it stands.'
    )
  }

  const gap = revised - flat
  // A shift smaller than this is the arithmetic of one ordinary day, not news.
  if (Math.abs(gap) < Math.max(0.01, flat * 0.01)) {
    return `${amount(revised, unit)} a day from here — the plan is holding.`
  }

  return gap < 0
    ? `${amount(revised, unit)} a day from here, down from the ` +
        `${amount(flat, unit)} originally planned. The overspend has to come ` +
        'out of the days that are left.'
    : `${amount(revised, unit)} a day from here, up from the ` +
        `${amount(flat, unit)} originally planned. The mission is running ` +
        'under, and the slack goes back to the days ahead.'
}

/** `MD-14 · day 14 of 30` — where the mission is, in one line. */
export function missionPosition(mission: MissionWindow): string {
  if (!mission.is_declared) return 'No mission declared'
  if (mission.state === 'before') return `Starts ${mission.start}`
  if (mission.state === 'after') return `Ended ${mission.end}`
  return `${mission.day_code} · day ${mission.day_index} of ${mission.days}`
}

/** When an extra lands, said the way the crew says it. */
export function extraWhen(extra: ExtraEntry): string {
  if (extra.kind === 'daily') return 'Every day'
  if (extra.stranded) return `${extra.on_date} · outside the mission`
  return extra.day_code ?? extra.on_date ?? '—'
}

/**
 * The day the calendar should scroll to on open.
 *
 * Today, or the first day if the mission has not started, or the last if it is
 * over — always a day that exists, so the caller never has to guard.
 */
export function focusDay(days: PlannedDay[]): PlannedDay | null {
  if (days.length === 0) return null
  return days.find((day) => day.state === 'today') ?? days[0]!
}
