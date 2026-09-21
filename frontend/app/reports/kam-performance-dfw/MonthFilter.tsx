"use client"

// Month selector for Loads Under 5% (Bruno PDF 2026-09-21). The other tabs
// filter by a RANGE (YTD/MTD/WTD/Custom); this one is defined per calendar
// month, so it gets its own control rather than a fifth preset that would then
// have to appear on five tabs that do not want it.
//
// ⚠ The default is the current month in CST, not in the browser's timezone —
// see `cstMonthNow()`. The list stops at that month: a future month is a blank
// table that reads as a broken report.

import { kamMonthOptions } from "@/lib/kam-performance-dfw-api"

export function MonthFilter({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  const options = kamMonthOptions()

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
        Month
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs text-[#374151]"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
