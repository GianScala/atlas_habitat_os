/**
 * Markdown rendering for assistant answers.
 *
 * Two overrides earn their place. Tables get their own horizontal scroller,
 * which stops a wide 90-row consumption table from forcing the whole page
 * sideways. And numeric cells are tagged so figures right-align on the
 * decimal point while words stay flush left — ATLAS's answers are mostly
 * per-period numbers, and a ragged column of them is hard to compare.
 */

import { memo, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownProps {
  children: string
}

/** Flatten a cell's children to plain text. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (typeof node === 'object' && 'props' in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children)
  }
  return ''
}

/**
 * A measurement, not a label: an optional sign, digits, and an optional unit
 * such as `21.4 °C` or `1,204 kWh`. A bare year or an ISO timestamp is left
 * alone — those read as identifiers, not quantities.
 */
const NUMERIC = /^[-+]?[\d,]+(\.\d+)?\s*[^\s\d]{0,8}$/

function isNumeric(value: string): boolean {
  const text = value.trim()
  if (!text || text === '—') return false
  if (/\d{4}-\d{2}-\d{2}/.test(text)) return false // a date or timestamp
  return NUMERIC.test(text)
}

function MarkdownImpl({ children }: MarkdownProps) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ node: _node, ...props }) => (
            <div className="markdown__table-wrap">
              <table {...props} />
            </div>
          ),
          td: ({ node: _node, children: cell, ...props }) => (
            <td className={isNumeric(textOf(cell)) ? 'is-numeric' : undefined} {...props}>
              {cell}
            </td>
          ),
          // Model-generated image URLs can transmit private text to remote hosts.
          img: ({ alt }) => <span>{alt ? `[Image: ${alt}]` : '[Image omitted]'}</span>,
          // Answers cite sensors, not the web; anything linked opens safely.
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer noopener" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

export const Markdown = memo(MarkdownImpl)
