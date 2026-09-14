/**
 * Series style assignment — a colour, and a stroke to go with it.
 *
 * Eight categorical slots, defined as CSS custom properties in `tokens.css`
 * so light and dark swap without any JavaScript. The values were validated
 * against this app's own chart surfaces — the full eight clear the lightness
 * band, chroma floor, colourblind separation and normal-vision floor in both
 * modes.
 *
 * Two rules the assignment exists to enforce:
 *
 *   Colour follows the entity, never its rank. A room keeps its colour when
 *   another room is toggled off, so the eye can track one line across
 *   filter changes.
 *
 *   No ninth hue is ever generated. The eight were checked as a set; a
 *   ninth invented at runtime has been checked against nothing.
 *
 * Past the eighth entity the palette starts a second lap — and the entities
 * on that lap are drawn dashed. A style is the PAIR, so the ninth room is a
 * dashed blue against the first room's solid blue rather than a second solid
 * blue that makes two rooms look like one. That is the same device already
 * used for a room reporting under two tag spellings, which is why the two
 * cases share one list of strokes: see `strokeFor`.
 */

const SLOTS = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
  'var(--series-7)',
  'var(--series-8)',
] as const

/**
 * Strokes, in the order they are handed out: solid first, then patterns
 * chosen to stay apart from one another at the 1.75px the charts draw at.
 *
 * The list is consumed two at a time — see `strokeFor`. Neighbours in it are
 * therefore the marks most likely to appear side by side in one colour, so
 * neighbours are the pairs that have to look different.
 */
const STROKES = ['', '10 4', '2 3', '9 3 2 3', '1 3', '14 3 2 3'] as const

/**
 * Strokes reserved per lap for one entity's own lines.
 *
 * Two, because a room reported under two tag spellings is the case that
 * exists and a third has never been seen. The reservation is what stops the
 * airlock's second sensor group from taking the exact mark — same colour,
 * same dash — already given to the rack eight slots later.
 */
const STROKES_PER_LAP = 2

export interface SeriesStyle {
  /** A CSS custom property reference, so the theme can swap underneath it. */
  colour: string
  /** Which lap of the palette this entity is on; 0 for the first eight. */
  lap: number
  /** The stroke for an entity drawing a single line — `strokeFor(style, 0)`. */
  dash: string
}

/**
 * A stable style per entity key.
 *
 * Assignment is by first appearance in a sorted key list, so it depends only
 * on which entities exist — not on which are currently visible, and not on
 * the order the server happened to return them.
 */
export function assignStyles(keys: string[]): Map<string, SeriesStyle> {
  const assignment = new Map<string, SeriesStyle>()

  ;[...keys].sort((a, b) => a.localeCompare(b)).forEach((key, index) => {
    const lap = Math.floor(index / SLOTS.length)
    assignment.set(key, {
      colour: SLOTS[index % SLOTS.length] as string,
      lap,
      dash: strokeAt(lap, 0),
    })
  })

  return assignment
}

/**
 * The stroke for the `position`-th line one entity draws on a panel.
 *
 * Position 0 is the entity's own stroke; further positions are the extra
 * lines where a room is reported under more than one tag spelling. Every
 * (lap, position) pair maps to its own place in the list, so no two series
 * sharing a colour can end up sharing a dash — which is the whole point of
 * spending a dash on them.
 */
export function strokeFor(style: SeriesStyle, position: number): string {
  return strokeAt(style.lap, position)
}

function strokeAt(lap: number, position: number): string {
  // Past the end the last stroke repeats rather than the list wrapping back
  // to solid: a 25th room is beyond what any encoding can separate, and
  // looking identical to the 1st is the one outcome to avoid.
  const slot = Math.min(lap * STROKES_PER_LAP + position, STROKES.length - 1)
  return STROKES[slot] as string
}

/** Grid, axis, and tooltip colours — recessive by design. */
export const CHART_INK = {
  grid: 'var(--chart-grid)',
  axis: 'var(--chart-axis)',
  label: 'var(--text-faint)',
  cursor: 'var(--chart-cursor)',
} as const
