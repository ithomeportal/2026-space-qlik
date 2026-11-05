"use client"

import {
  fmtInt,
  fmtMonths,
  fmtPct,
  fmtUsdCompact,
  useSummary,
  type Division,
  type RangeKey,
  type ReportFilters,
  type Window,
} from "@/lib/customer-lifespan-api"
import { ErrorBox, Loading } from "./ui"

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-[#E5E7EB] bg-white px-3 py-2.5 shadow-sm">
      <div className="text-[11px] uppercase leading-tight tracking-wide text-[#6B7280]">{label}</div>
      <div className={`mt-0.5 text-xl font-semibold tabular-nums ${tone ?? "text-[#111827]"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-tight text-[#6B7280]">{sub}</div>}
    </div>
  )
}

/** The period a tile counts, in its title. A custom range is too long to fit one. */
function periodOf(range: RangeKey, label: string): { short: string; long: string; phrase: string } {
  if (range === "last_365") return { short: "Last 12 mo", long: "Last 12 months", phrase: "past 12 months" }
  if (range === "custom") return { short: "Selected dates", long: "Selected dates", phrase: "the selected dates" }
  return { short: label, long: label, phrase: range === "all" ? "the whole history" : label }
}

export function KpiStrip({ division, window, filters }: {
  division: Division
  window: Window
  filters: ReportFilters
}) {
  const { data, error, isLoading } = useSummary(division, window, filters)
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading height="h-20" />
  const s = data.data
  const p = periodOf(data.meta.range, data.meta.range_label)
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
      <Tile
        label="Current customers"
        value={fmtInt(s.base)}
        sub={`Shipped in past ${window} days · ${fmtInt(s.customers_total)} all-time`}
        tone="text-[#1B3A5C]"
      />
      <Tile label="Active" value={fmtInt(s.active)} sub="Shipped in past 30 days" tone="text-[#059669]" />
      <Tile label="At risk" value={fmtInt(s.at_risk)} sub={`Last load 31–${window} days ago`} tone="text-[#D97706]" />
      <Tile label={`New customers · ${p.short}`} value={fmtInt(s.new_period)} sub={`First load in ${p.phrase}`} />
      <Tile
        label={`Lost customers · ${p.short}`}
        value={fmtInt(s.lost_period)}
        sub={`No loads for over ${window} days`}
        tone="text-[#DC2626]"
      />
      <Tile
        label="Avg. lifespan · Lost customers"
        value={fmtMonths(s.avg_lifespan_lost)}
        sub={`Median: ${fmtMonths(s.median_lifespan_lost)}`}
      />
      <Tile
        label="Avg. lifespan · Current customers"
        value={fmtMonths(s.avg_lifespan_base)}
        sub="First to most recent load · To date"
      />
      <Tile
        label={`Revenue · ${p.long}`}
        value={fmtUsdCompact(s.revenue_period)}
        sub={`Top 10 customers: ${fmtPct(s.top10_share, 0)} · Margin: ${fmtUsdCompact(s.margin_period)}`}
      />
    </div>
  )
}
