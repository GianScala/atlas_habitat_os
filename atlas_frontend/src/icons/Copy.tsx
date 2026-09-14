import { iconAttrs, type IconProps } from './icon'

export function Copy({ size = 13, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      {/* The sheet in front, and the corner of the one behind it. */}
      <path d="M6 6h7v7.5H6z" />
      <path d="M10.5 3.5V2.5H3v7.5h1" />
    </svg>
  )
}
