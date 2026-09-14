/**
 * The legend.
 *
 * Always present when a chart carries more than one series, and every entry
 * pairs a swatch with a written name — so a reader who cannot separate two
 * hues still has the label. A single-series chart gets none: its title
 * already names the line.
 *
 * Clicking an entry isolates that series, which is the cheap way to read one
 * room out of a crowded chart without touching the filter above.
 */

interface LegendEntry {
  key: string
  label: string
  colour: string
  /** True where something else on this dashboard is drawn in the same colour. */
  dashed: boolean
}

interface ChartLegendProps {
  entries: LegendEntry[]
  /** Key of the isolated series, or null when all are shown. */
  isolated: string | null
  onIsolate: (key: string | null) => void
}

export function ChartLegend({ entries, isolated, onIsolate }: ChartLegendProps) {
  if (entries.length < 2) return null

  return (
    <ul className="legend">
      {entries.map((entry) => {
        const dimmed = isolated !== null && isolated !== entry.key
        return (
          <li key={entry.key}>
            <button
              type="button"
              className={dimmed ? 'legend__item legend__item--dimmed' : 'legend__item'}
              onClick={() => onIsolate(isolated === entry.key ? null : entry.key)}
              aria-pressed={isolated === entry.key}
              title={
                isolated === entry.key
                  ? 'Show all series'
                  : entry.dashed
                    ? `Show only ${entry.label}, drawn dashed because something ` +
                      `else on this dashboard already has this colour, so the ` +
                      `two are never mistaken for one`
                    : `Show only ${entry.label}`
              }
            >
              {/* `color` rather than `background`, so the dashed variant can
                  build its pattern out of the same value. */}
              <span
                className={
                  entry.dashed ? 'legend__swatch legend__swatch--dashed' : 'legend__swatch'
                }
                style={{ color: entry.colour }}
                aria-hidden
              />
              {entry.label}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
