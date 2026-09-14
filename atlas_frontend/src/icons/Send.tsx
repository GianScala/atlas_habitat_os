import { iconAttrs, type IconProps } from './icon'

export function Send({ size = 16, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M14.5 1.5L7 9" />
      <path d="M14.5 1.5l-4.8 13-2.7-5.5L1.5 6.3z" />
    </svg>
  )
}
