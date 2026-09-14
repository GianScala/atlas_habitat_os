import { iconAttrs, type IconProps } from './icon'

export function ChartIcon({ size = 15, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M2 13.5h12" />
      <path d="M4 13.5V8" />
      <path d="M7.3 13.5V4.5" />
      <path d="M10.7 13.5V10" />
      <path d="M14 13.5V6.5" />
    </svg>
  )
}
