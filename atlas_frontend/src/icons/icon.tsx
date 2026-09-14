/**
 * The drawing contract every icon in this folder keeps.
 *
 * All of them are drawn on the same 16px grid and stroked in `currentColor`,
 * so an icon takes the colour of the control it sits in and needs no theme
 * awareness of its own. `size` is the rendered box; the viewBox never
 * changes, so an icon scales without its stroke weight drifting.
 *
 * Kept local rather than pulled from an icon package: there is a handful of
 * them, they are a few paths each, and a dependency for this would be silly.
 * To add one, copy the smallest file here, draw on the 16 grid, and export it
 * from `index.ts`.
 */

export interface IconProps {
  /** Rendered width and height in px. The viewBox stays at 16. */
  size?: number
  className?: string
}

/**
 * Shared SVG attributes. Square caps are used where a shape is a mark rather
 * than a stroke; those icons override `strokeLinecap` themselves.
 */
export const iconAttrs = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
})
