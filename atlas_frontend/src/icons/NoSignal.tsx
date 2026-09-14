import { iconAttrs, type IconProps } from './icon'

/** A plot with the trace missing — "the query ran, nothing came back". */
export function NoSignal({ size = 18, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <path d="M2 2.5v11h12" />
      <path d="M4.6 10.4h.01" />
      <path d="M7.4 10.4h.01" />
      <path d="M10.2 10.4h.01" />
      <path d="M13 10.4h.01" />
    </svg>
  )
}
