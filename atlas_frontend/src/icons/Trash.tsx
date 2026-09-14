import { iconAttrs, type IconProps } from './icon'

export function Trash({ size = 13, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M2.5 4h11" />
      <path d="M6 4V2.5h4V4" />
      <path d="M3.8 4l.7 9.2c.04.5.46.8.9.8h5.2c.44 0 .86-.3.9-.8L12.2 4" />
    </svg>
  )
}
