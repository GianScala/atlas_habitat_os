/**
 * Every icon in the app, in one import.
 *
 *   import { Send, Stop } from '@/icons'
 *
 * One file per icon, all drawn against the contract in `icon.tsx`. The barrel
 * is re-exports only, so the bundler still drops the ones a page never uses.
 */

export type { IconProps } from './icon'
export { iconAttrs } from './icon'

/* --- Direction --- */
export { ChevronDown } from './ChevronDown'
export { ChevronLeft } from './ChevronLeft'
export { ChevronRight } from './ChevronRight'

/* --- Actions --- */
export { Check } from './Check'
export { Copy } from './Copy'
export { Download } from './Download'
export { Plus } from './Plus'
export { Refresh } from './Refresh'
export { Mic } from './Mic'
export { Send } from './Send'
export { Speaker } from './Speaker'
export { Stop } from './Stop'
export { Trash } from './Trash'

/* --- Navigation --- */
export { ChartIcon } from './ChartIcon'
export { ChatIcon } from './ChatIcon'
export { Chip } from './Chip'
export { Contrast } from './Contrast'
export { Rooms } from './Rooms'
export { Settings } from './Settings'

/* --- States --- */
export { NoSignal } from './NoSignal'
export { Warning } from './Warning'
export { Logo } from './Logo'
