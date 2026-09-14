import { iconAttrs, type IconProps } from './icon'

export function ChevronDown({ size = 12, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M3 6l5 5 5-5" />
    </svg>
  )
}
