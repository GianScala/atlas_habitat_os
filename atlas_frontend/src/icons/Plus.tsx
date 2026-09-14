import { iconAttrs, type IconProps } from './icon'

export function Plus({ size = 14, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M8 3v10M3 8h10" />
    </svg>
  )
}
