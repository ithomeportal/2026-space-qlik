"use client"

// Bruno R7 (2026-05-26): clicking a Customer cell in any table sets the global
// Customer filter. When no handler is wired (or the row is the "Others"/blank
// aggregate) it renders as plain text so totals rows aren't clickable.
interface CustomerLinkProps {
  name: string
  onSelect?: (customer: string) => void
  className?: string
}

const NON_FILTERABLE = new Set(["Others", "Totals", "", "—"])

export function CustomerLink({ name, onSelect, className = "" }: CustomerLinkProps) {
  if (!onSelect || NON_FILTERABLE.has(name)) {
    return <span className={className}>{name}</span>
  }
  return (
    <button
      type="button"
      onClick={() => onSelect(name)}
      title={`Filter by ${name}`}
      className={`text-left underline-offset-2 hover:text-[#1B3A5C] hover:underline focus:underline focus:outline-none ${className}`}
    >
      {name}
    </button>
  )
}
