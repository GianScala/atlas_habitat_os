import { iconAttrs, type IconProps } from './icon'

/**
 * A square, half of it inked — the theme control's mark.
 *
 * A square rather than the usual half-moon, because every other shape in this
 * interface is one, and because the icon is literally what the button does:
 * swap which half of the palette is paper and which is ink.
 */
export function Contrast({ size = 15, className }: IconProps) {
  return (
    <svg {...iconAttrs(size)} className={className}>
      <rect x="2.5" y="2.5" width="11" height="11" />
      <path d="M8 2.5h5.5v11H8z" fill="currentColor" stroke="none" />
    </svg>
  )
}
