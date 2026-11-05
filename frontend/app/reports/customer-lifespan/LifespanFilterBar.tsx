"use client"

import { useMemo, useState } from "react"
import { CollapsibleFilterBar } from "@/components/CollapsibleFilterBar"
import { useFilterOptions, type Division, type RangeKey, type ReportFilters } from "@/lib/customer-lifespan-api"

// As in Sales- Attrition to OPs, plus "All time": the report goes back to 2016.
const RANGES: { key: RangeKey; label: string }[] = [
  { key: "last_365", label: "Last 365d" },
  { key: "mtd", label: "MTD" },
  { key: "last_month", label: "Last month" },
  { key: "ytd", label: "YTD" },
  { key: "all", label: "All time" },
  { key: "custom", label: "Custom" },
]

const MAX_SUGGESTIONS = 25
const CHIP_LABELS: Record<string, string> = { "NO TEAM": "No team (before 2021)", OTHER: "Other" }

export function LifespanFilterBar({ division, value, onChange }: {
  division: Division
  value: ReportFilters
  onChange: (patch: Partial<ReportFilters>) => void
}) {
  const { data } = useFilterOptions(division)
  const chips = useMemo(() => data?.data.teams ?? [], [data])
  const customers = useMemo(() => data?.data.customers ?? [], [data])
  const [typed, setTyped] = useState("")
  const label = customers.find((c) => c.customer_id === value.customer)?.name ?? value.customer

  const suggestions = useMemo(() => {
    const q = typed.trim().toLowerCase()
    if (!q) return []
    return customers
      .filter((c) => c.name.toLowerCase().includes(q) || c.customer_id.toLowerCase().includes(q))
      .slice(0, MAX_SUGGESTIONS)
  }, [typed, customers])

  // A selection from another division may hold chips this one lacks.
  const selected = value.teams === null ? chips : value.teams.filter((t) => chips.includes(t))
  const toggleTeam = (t: string) => {
    const next = selected.includes(t) ? selected.filter((x) => x !== t) : [...selected, t]
    onChange({ teams: next.length === chips.length ? null : next })
  }
  const dateClass = "rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
  const badRange = value.range === "custom" && value.start && value.end && value.start > value.end

  return (
    <CollapsibleFilterBar>
      <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center gap-4 px-6 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Date</span>
          <div className="flex flex-wrap rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => onChange({ range: r.key })}
                className={`px-3 py-1.5 ${
                  value.range === r.key ? "bg-white font-semibold text-[#1B3A5C] shadow-sm" : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          {value.range === "custom" && (
            <div className="flex items-center gap-1">
              <input type="date" value={value.start} onChange={(e) => onChange({ start: e.target.value })} className={dateClass} />
              <span className="text-[#6B7280]">→</span>
              <input type="date" value={value.end} onChange={(e) => onChange({ end: e.target.value })} className={dateClass} />
              {badRange && <span className="text-xs text-[#DC2626]">Start is after end</span>}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Teams</span>
          <div className="flex flex-wrap gap-1">
            {chips.map((t) => (
              <button
                key={t}
                onClick={() => toggleTeam(t)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  selected.includes(t)
                    ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                    : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                }`}
              >
                {CHIP_LABELS[t] ?? t}
              </button>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">Customer</span>
          <input
            type="text"
            placeholder={label || "All customers"}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onBlur={() => setTimeout(() => setTyped(""), 150)}
            className="w-64 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
          />
          {typed && suggestions.length > 0 && (
            <ul className="absolute left-[4.5rem] top-full z-30 mt-1 max-h-64 w-64 overflow-auto rounded-md border border-[#E5E7EB] bg-white text-xs shadow-md">
              {suggestions.map((c) => (
                <li key={c.customer_id}>
                  <button
                    onMouseDown={() => {
                      onChange({ customer: c.customer_id })
                      setTyped("")
                    }}
                    className="block w-full truncate px-3 py-1.5 text-left hover:bg-[#F3F4F6]"
                  >
                    {c.name} <span className="ml-1 text-[#6B7280]">{c.customer_id}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {value.customer && (
            <button
              onClick={() => onChange({ customer: "" })}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#6B7280] hover:bg-[#F3F4F6]"
            >
              Clear
            </button>
          )}
        </div>
      </div>
    </CollapsibleFilterBar>
  )
}
