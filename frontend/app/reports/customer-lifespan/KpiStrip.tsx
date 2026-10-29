"use client"

import {
  fmtInt,
  fmtMonths,
  fmtPct,
  fmtUsdCompact,
  useSummary,
  type Division,
  type Window,
} from "@/lib/customer-lifespan-api"
import { ErrorBox, Loading } from "./ui"

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-[#E5E7EB] bg-white px-3 py-2.5 shadow-sm">
      <div className="truncate text-[11px] uppercase tracking-wide text-[#6B7280]">{label}</div>
      <div className={`mt-0.5 text-xl font-semibold tabular-nums ${tone ?? "text-[#111827]"}`}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-[#6B7280]">{sub}</div>}
    </div>
  )
}

export function KpiStrip({ division, window }: { division: Division; window: Window }) {
  const { data, error, isLoading } = useSummary(division, window)
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading height="h-20" />
  const s = data.data
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
      <Tile
        label="Customer base"
        value={fmtInt(s.base)}
        sub={`load in last ${window} days · ${fmtInt(s.customers_total)} ever`}
        tone="text-[#1B3A5C]"
      />
      <Tile label="Active" value={fmtInt(s.active)} sub="load in last 30 days" tone="text-[#059669]" />
      <Tile label="At risk" value={fmtInt(s.at_risk)} sub={`quiet 31–${window} days`} tone="text-[#D97706]" />
      <Tile label="New · last 12 mo" value={fmtInt(s.new_12m)} sub={`${fmtInt(s.new_ytd)} this year`} />
      <Tile
        label="Lost · last 12 mo"
        value={fmtInt(s.lost_12m)}
        sub={`${fmtInt(s.reactivated_12m)} came back`}
        tone="text-[#DC2626]"
      />
      <Tile
        label="Lifespan of lost"
        value={fmtMonths(s.avg_lifespan_lost)}
        sub={`median ${fmtMonths(s.median_lifespan_lost)}`}
      />
      <Tile label="Lifespan of base" value={fmtMonths(s.avg_lifespan_base)} sub="first → last load, so far" />
      <Tile
        label="Revenue · last 12 mo"
        value={fmtUsdCompact(s.revenue_12m)}
        sub={`top 10 = ${fmtPct(s.top10_share_12m, 0)} · margin ${fmtUsdCompact(s.margin_12m)}`}
      />
    </div>
  )
}
