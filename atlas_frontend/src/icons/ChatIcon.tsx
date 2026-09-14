import { iconAttrs, type IconProps } from './icon'

export function ChatIcon({ size = 15, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M14 9.5a2 2 0 0 1-2 2H6l-3.5 2.5V4a2 2 0 0 1 2-2h7.5a2 2 0 0 1 2 2z" />
    </svg>
  )
}
