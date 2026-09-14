import { iconAttrs, type IconProps } from './icon'

export function Check({ size = 13, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M3 8.5L6.2 11.7 13 5" />
    </svg>
  )
}
