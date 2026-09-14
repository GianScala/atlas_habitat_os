import { iconAttrs, type IconProps } from './icon'

/** A filled square — the mark, not an outline, so it reads at any size. */
export function Stop({ size = 16, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <rect x="4" y="4" width="8" height="8" fill="currentColor" />
    </svg>
  )
}
