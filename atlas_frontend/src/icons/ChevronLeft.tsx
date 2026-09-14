import { iconAttrs, type IconProps } from './icon'

export function ChevronLeft({ size = 12, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M10 3L5 8l5 5" />
    </svg>
  )
}
