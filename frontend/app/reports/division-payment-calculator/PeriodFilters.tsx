"use client"

import { Calendar } from "lucide-react"

import type { Periods } from "@/lib/division-payment-api"
import { DPC } from "./theme"

interface Props {
  periods: Periods | undefined
  year: number | null
  month: string | null
  onChange: (year: number, month: string) => void
  label?: string
}

/**
 * Year + Month/Year filters (PDF Dashboard Request 1, Calculator Request 1).
 *
 * Native `<select>` on purpose: this frontend is React 18 and shadcn's Select
 * sits on `@base-ui/react`, which the project bans in interactive components on
 * React 18. Every other report's filters here are native selects too.
 *
 * Changing the year keeps the same month when that year has it, and otherwise
 * falls back to the year's last available month — the prototype left the
 * dropdown showing a month whose data it was not displaying.
 */
export function PeriodFilters({ periods, year, month, onChange, label }: Props) {
  const years = periods?.years ?? []
  const monthsInYear = (periods?.months ?? []).filter((m) => m.year === year)

  const handleYear = (nextYear: number) => {
    const inYear = (periods?.months ?? []).filter((m) => m.year === nextYear)
    if (inYear.length === 0) return
    const same = inYear.find((m) => m.month === month)
    onChange(nextYear, (same ?? inYear[inYear.length - 1]).month)
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {label ? (
        <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[#6B7280]">
          <Calendar className="h-3.5 w-3.5" aria-hidden />
          {label}
        </span>
      ) : null}

      <select
        aria-label="Year"
        value={year ?? ""}
        onChange={(e) => handleYear(Number(e.target.value))}
        className="rounded-md border border-[#E5E7EB] bg-white px-2.5 py-1.5 text-sm font-medium"
      >
        {years.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>

      <select
        aria-label="Month"
        value={month ?? ""}
        onChange={(e) => onChange(year!, e.target.value)}
        className="rounded-md border border-[#E5E7EB] bg-white px-2.5 py-1.5 text-sm font-medium"
      >
        {monthsInYear.map((m) => (
          <option key={m.month} value={m.month}>
            {m.month_label}
            {m.has_recalc ? " •" : ""}
          </option>
        ))}
      </select>

      {monthsInYear.some((m) => m.has_recalc) ? (
        <span className="text-[10px] text-[#9CA3AF]" style={{ color: DPC.gold }}>
          • carries a recalculation
        </span>
      ) : null}
    </div>
  )
}
