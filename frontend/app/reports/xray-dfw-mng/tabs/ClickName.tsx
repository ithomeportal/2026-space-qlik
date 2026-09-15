"use client"

/**
 * Click-to-filter name cell.
 *
 * Extracted from `ContractSpot.tsx` on 2026-09-15 when the All Orders table
 * moved into its own component and would otherwise have become a third copy.
 * `CustomersLanes.tsx` still carries its own (narrower, no `display`) copy —
 * it is an unrelated tab and was left alone rather than swept into this round.
 */
export function ClickName({
  value,
  display,
  onClick,
}: {
  value: string
  display?: string
  onClick?: (v: string) => void
}) {
  const text = display ?? value
  if (!onClick) return <>{text}</>
  return (
    <button
      type="button"
      onClick={() => onClick(value)}
      className="text-left hover:text-[#1B3A5C] hover:underline"
      title="Filter by this value"
    >
      {text}
    </button>
  )
}
