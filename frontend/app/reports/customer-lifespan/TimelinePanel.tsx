"use client"

import { useMemo, useState } from "react"
import { STATUS_META, fmtDate, fmtMonths, fmtUsdCompact, type CustomerRow } from "@/lib/customer-lifespan-api"
import { Segmented } from "./ui"

const SORTS = [
  { k: "first", label: "First load" },
  { k: "revenue", label: "Revenue" },
  { k: "lifespan", label: "Lifespan" },
] as const
type SortKey = (typeof SORTS)[number]["k"]

const LIMITS = [
  { k: 50, label: "Top 50" },
  { k: 150, label: "Top 150" },
  { k: 0, label: "All" },
] as const

const idx = (ym: string) => {
  const [y, m] = ym.split("-").map(Number)
  return y * 12 + (m - 1)
}

const SORTERS: Record<SortKey, (a: CustomerRow, b: CustomerRow) => number> = {
  first: (a, b) => a.first_ship.localeCompare(b.first_ship),
  revenue: (a, b) => b.revenue - a.revenue,
  lifespan: (a, b) => b.lifespan_months - a.lifespan_months || b.revenue - a.revenue,
}

/** One lane per customer: a bar from first to last load, a tick per month with a load. */
export function TimelinePanel({ rows, asOf, onOpen }: {
  rows: CustomerRow[]
  asOf: string
  onOpen: (id: string) => void
}) {
  const [sort, setSort] = useState<SortKey>("first")
  const [limit, setLimit] = useState<number>(150)
  const lanes = useMemo(() => {
    const byRevenue = limit ? [...rows].sort(SORTERS.revenue).slice(0, limit) : rows
    return [...byRevenue].sort(SORTERS[sort])
  }, [rows, sort, limit])

  if (rows.length === 0) return <div className="py-6 text-center text-xs text-[#6B7280]">No customer matches these filters.</div>
  const start = Math.min(...rows.map((r) => idx(r.first_ship.slice(0, 7))))
  const end = idx(asOf.slice(0, 7))
  const span = Math.max(end - start + 1, 1)
  const x = (i: number) => `${((i - start) / span) * 100}%`
  const w = (n: number) => `${(n / span) * 100}%`
  const years = Array.from({ length: Math.floor(end / 12) - Math.floor(start / 12) + 1 }, (_, k) => Math.floor(start / 12) + k)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Sort" value={sort} options={SORTS} onChange={setSort} />
        <Segmented label="Show" value={limit} options={LIMITS} onChange={setLimit} />
        <span className="text-[11px] text-[#6B7280]">
          {limit ? `the ${limit} largest customers by lifetime revenue` : "every customer"} in the current filters · light bar = lifespan, dark ticks = months with loads
        </span>
      </div>
      <div className="max-h-[70vh] overflow-y-auto rounded-lg border border-[#E5E7EB]">
        <div className="sticky top-0 z-10 flex border-b border-[#E5E7EB] bg-[#F9FAFB] text-[10px] text-[#6B7280]">
          <div className="w-56 shrink-0 px-2 py-1">Customer</div>
          <div className="relative h-5 flex-1">
            {years.map((y) => (
              <span key={y} className="absolute top-1 -translate-x-1/2" style={{ left: x(Math.max(y * 12, start)) }}>{y}</span>
            ))}
          </div>
        </div>
        {lanes.map((r) => {
          const first = idx(r.first_ship.slice(0, 7))
          const last = idx(r.last_ship.slice(0, 7))
          const color = STATUS_META[r.status].color
          return (
            <button
              key={r.customer_id}
              onClick={() => onOpen(r.customer_id)}
              className="flex w-full items-center border-b border-[#F9FAFB] text-left hover:bg-[#F9FAFB]"
              title={`${r.name} · ${fmtDate(r.first_ship)} → ${fmtDate(r.last_ship)} · ${fmtMonths(r.lifespan_months)} · ${fmtUsdCompact(r.revenue)}`}
            >
              <div className="w-56 shrink-0 truncate px-2 py-1 text-[11px] text-[#111827]">{r.name}</div>
              <div className="relative h-4 flex-1">
                {years.map((y) => (
                  <span key={y} className="absolute inset-y-0 w-px bg-[#F3F4F6]" style={{ left: x(y * 12) }} />
                ))}
                <span className="absolute top-1/2 h-2 -translate-y-1/2 rounded-sm" style={{ left: x(first), width: w(last - first + 1), background: color, opacity: 0.18 }} />
                {r.months_active.map((m) => (
                  <span key={m} className="absolute top-1/2 h-2.5 -translate-y-1/2" style={{ left: x(idx(m)), width: `max(1px, ${w(1)})`, background: color }} />
                ))}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
