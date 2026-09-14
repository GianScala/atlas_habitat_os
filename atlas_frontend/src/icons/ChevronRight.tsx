import { iconAttrs, type IconProps } from './icon'

export function ChevronRight({ size = 12, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M6 3l5 5-5 5" />
    </svg>
  )
}
