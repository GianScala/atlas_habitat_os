import { iconAttrs, type IconProps } from './icon'

export function Refresh({ size = 14, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M13.5 7a5.5 5.5 0 1 0-.9 4" />
      <path d="M13.5 2.8V7h-4.2" />
    </svg>
  )
}
