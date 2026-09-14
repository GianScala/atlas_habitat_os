import { iconAttrs, type IconProps } from './icon'

/**
 * A gear — the one mark everyone already reads as "settings".
 *
 * Drawn as two circles and eight spokes rather than a toothed outline: at
 * 15px a real cog silhouette turns to mush, and this keeps the same even
 * stroke weight as every other icon here.
 */
export function Settings({ size = 15, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <circle cx="8" cy="8" r="2.2" />
      <circle cx="8" cy="8" r="5.2" />
      <path d="M8 1.2v1.6M8 13.2v1.6M1.2 8h1.6M13.2 8h1.6M3.2 3.2l1.1 1.1M11.7 11.7l1.1 1.1M12.8 3.2l-1.1 1.1M4.3 11.7l-1.1 1.1" />
    </svg>
  )
}
