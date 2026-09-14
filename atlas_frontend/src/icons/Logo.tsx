import { iconAttrs, type IconProps } from './icon'

/**
 * ATLAS "A" mark.
 *
 * NASA-inspired aerospace wordmark geometry:
 * wide stance, rounded apex, no crossbar.
 *
 * Uses currentColor so it automatically adapts
 * to light/dark themes.
 */
export function Logo({ size = 18, className }: IconProps) {
  return (
    <svg
      {...iconAttrs(size)}
      className={className}
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        stroke="none"
        d="
          M1.35 13.5
          L5.62 3.18
          C6.08 2.06 6.82 1.45 8 1.45
          C9.18 1.45 9.92 2.06 10.38 3.18
          L14.65 13.5
          H12.28
          L8.75 5.02
          C8.58 4.60 8.34 4.38 8 4.38
          C7.66 4.38 7.42 4.60 7.25 5.02
          L3.72 13.5
          Z
        "
      />
    </svg>
  )
}