import { iconAttrs, type IconProps } from './icon'

/** Two rooms side by side — the room filter's mark. */
export function Rooms({ size = 18, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <rect x="1.8" y="3.5" width="5.4" height="9" />
      <rect x="8.8" y="3.5" width="5.4" height="9" />
    </svg>
  )
}
