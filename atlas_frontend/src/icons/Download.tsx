import { iconAttrs, type IconProps } from './icon'

export function Download({ size = 13, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M8 2v8" />
      <path d="M4.5 7L8 10.5 11.5 7" />
      <path d="M2.5 13.5h11" />
    </svg>
  )
}
