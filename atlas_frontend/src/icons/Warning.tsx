import { iconAttrs, type IconProps } from './icon'

export function Warning({ size = 15, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M8 1.8L15 14H1z" />
      <path d="M8 6.5v3.2" />
      <circle cx="8" cy="11.8" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  )
}
