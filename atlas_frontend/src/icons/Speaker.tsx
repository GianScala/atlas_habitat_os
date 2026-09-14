import { iconAttrs, type IconProps } from './icon'

export function Speaker({ size = 16, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M2 6h3l4-3v10l-4-3H2zM11.5 5.25a4 4 0 0 1 0 5.5M13.5 3a7 7 0 0 1 0 10" />
    </svg>
  )
}
