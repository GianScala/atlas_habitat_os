/** A processor die with its pins: the model, and the machine it runs on. */

import { iconAttrs, type IconProps } from './icon'

export function Chip({ size = 13, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className} strokeLinecap="square">
      <rect x="4.5" y="4.5" width="7" height="7" />
      <path d="M6.5 2v2.5M9.5 2v2.5M6.5 11.5V14M9.5 11.5V14" />
      <path d="M2 6.5h2.5M2 9.5h2.5M11.5 6.5H14M11.5 9.5H14" />
    </svg>
  )
}
