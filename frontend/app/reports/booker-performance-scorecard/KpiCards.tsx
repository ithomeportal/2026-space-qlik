"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsd2,
  useBookerSummary,
  type BookerFilters,
} from "@/lib/booker-scorecard-api"

interface Props {
  filters: BookerFilters
}

interface CardProps {
  label: string
  value: string
  sub?: string
  title?: string
  tone?: "default" | "warn"
}

function Card({ label, value, sub, title, tone = "default" }: CardProps) {
  return (
    <div
      className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm"
      title={title}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div
        className={`mt-1 text-xl font-semibold ${
          tone === "warn" ? "text-[#B45309]" : "text-[#1B3A5C]"
        }`}
      >
        {value}
      </div>
      {/* Always render the slot so the cards keep a uniform height. */}
      <div className="mt-0.5 h-4 text-[10px] text-[#9CA3AF]">{sub ?? ""}</div>
    </div>
  )
}

export function KpiCards({ filters }: Props) {
  const { data, isLoading, error } = useBookerSummary(filters)
  const k = data?.data

  if (error) {
    return (
      <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
        Could not load KPIs: {error instanceof Error ? error.message : "unknown error"}
      </div>
    )
  }

  if (isLoading && !k) {
    return (
      <div className="flex h-24 items-center justify-center rounded-xl border border-[#E5E7EB] bg-white">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  // Broken Threshold is only meaningful against the number of orders that
  // actually carry a threshold — thresholds are hand-entered in Loads to Cover,
  // so roughly 40% of bookings have none. Showing the bare count would imply a
  // coverage this data does not have.
  const brokenSub =
    k?.broken_threshold === null || k?.broken_threshold === undefined
      ? "threshold source unavailable"
      : `of ${fmtCount(k.threshold_orders)} orders with a threshold`

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      <Card label="# Orders" value={fmtCount(k?.orders)} />
      <Card label="Profit" value={fmtUsd(k?.profit)} />
      <Card
        label="Margin %"
        value={fmtPct(k?.margin_pct)}
        sub="Σ profit ÷ Σ revenue"
      />
      <Card
        label="Avg Margin / Load"
        value={fmtUsd2(k?.avg_margin_per_load)}
        sub="profit ÷ # orders"
      />
      <Card
        label="Broken Threshold"
        value={fmtCount(k?.broken_threshold)}
        sub={brokenSub}
        tone={k?.broken_threshold ? "warn" : "default"}
        title="Orders where Carrier Cost (Revenue − Profit) exceeds the threshold typed in Loads to Cover. Orders with no threshold are excluded from both numbers."
      />
      <Card
        label="OTP"
        value={fmtPct(k?.otp_pct)}
        sub="on-time pickup"
        title="1 − late pickups ÷ orders. An order with no service incident counts as on time, so loads not yet picked up read as on-time — expect ~100% on a Today window."
      />
      <Card
        label="OTD"
        value={fmtPct(k?.otd_pct)}
        sub="on-time delivery"
        title="1 − late deliveries ÷ orders. An order with no service incident counts as on time, so loads not yet delivered read as on-time — expect ~100% on a Today window."
      />
    </div>
  )
}
