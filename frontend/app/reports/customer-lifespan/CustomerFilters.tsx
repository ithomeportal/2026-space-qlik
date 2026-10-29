"use client"

import { Search } from "lucide-react"
import { STATUS_META, type CustomerRow, type Status } from "@/lib/customer-lifespan-api"

export interface Filters {
  q: string
  statuses: Status[]
  cohortFrom: number | null
  cohortTo: number | null
  minRevenue: number
  reactivatedOnly: boolean
}

export const EMPTY_FILTERS: Filters = {
  q: "", statuses: [], cohortFrom: null, cohortTo: null, minRevenue: 0, reactivatedOnly: false,
}

const MIN_REVENUE = [
  { v: 0, label: "Any revenue" },
  { v: 10_000, label: "≥ $10K lifetime" },
  { v: 100_000, label: "≥ $100K lifetime" },
  { v: 1_000_000, label: "≥ $1M lifetime" },
]

export function applyFilters(rows: CustomerRow[], f: Filters): CustomerRow[] {
  const q = f.q.trim().toLowerCase()
  return rows.filter((r) =>
    (!q || r.name.toLowerCase().includes(q) || r.customer_id.toLowerCase().includes(q))
    && (f.statuses.length === 0 || f.statuses.includes(r.status))
    && (f.cohortFrom === null || r.cohort_year >= f.cohortFrom)
    && (f.cohortTo === null || r.cohort_year <= f.cohortTo)
    && r.revenue >= f.minRevenue
    && (!f.reactivatedOnly || r.reactivations > 0))
}

export function CustomerFilters({ value, onChange, years, shown, total }: {
  value: Filters
  onChange: (f: Filters) => void
  years: number[]
  shown: number
  total: number
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...value, ...patch })
  const toggle = (s: Status) =>
    set({ statuses: value.statuses.includes(s) ? value.statuses.filter((x) => x !== s) : [...value.statuses, s] })
  const sel = "rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <label className="flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1">
        <Search className="h-3.5 w-3.5 text-[#9CA3AF]" />
        <input
          value={value.q}
          onChange={(e) => set({ q: e.target.value })}
          placeholder="Customer name or ID"
          className="w-44 bg-transparent outline-none"
        />
      </label>
      {(Object.keys(STATUS_META) as Status[]).map((s) => (
        <button
          key={s}
          onClick={() => toggle(s)}
          className={`rounded-full border px-2.5 py-1 ${
            value.statuses.includes(s) ? `${STATUS_META[s].chip} border-transparent font-medium` : "border-[#E5E7EB] bg-white text-[#6B7280]"
          }`}
        >
          {STATUS_META[s].label}
        </button>
      ))}
      <span className="text-[#6B7280]">First load</span>
      <select className={sel} value={value.cohortFrom ?? ""} onChange={(e) => set({ cohortFrom: e.target.value ? Number(e.target.value) : null })}>
        <option value="">from any</option>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
      <select className={sel} value={value.cohortTo ?? ""} onChange={(e) => set({ cohortTo: e.target.value ? Number(e.target.value) : null })}>
        <option value="">to any</option>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
      <select className={sel} value={value.minRevenue} onChange={(e) => set({ minRevenue: Number(e.target.value) })}>
        {MIN_REVENUE.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
      </select>
      <label className="flex items-center gap-1 text-[#374151]">
        <input type="checkbox" checked={value.reactivatedOnly} onChange={(e) => set({ reactivatedOnly: e.target.checked })} />
        came back at least once
      </label>
      <button onClick={() => onChange(EMPTY_FILTERS)} className="text-[#1B3A5C] underline-offset-2 hover:underline">
        Reset
      </button>
      <span className="ml-auto text-[#6B7280]">{shown} of {total} customers</span>
    </div>
  )
}
