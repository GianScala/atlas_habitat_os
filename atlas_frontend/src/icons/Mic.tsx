import { iconAttrs, type IconProps } from './icon'

export function Mic({ size = 16, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <rect x="5.25" y="1.5" width="5.5" height="9" rx="2.75" />
      <path d="M3 7.75a5 5 0 0 0 10 0M8 12.75v2.25M5.5 15h5" />
    </svg>
  )
}
