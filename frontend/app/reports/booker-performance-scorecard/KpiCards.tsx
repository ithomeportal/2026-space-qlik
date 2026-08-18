"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsd2,
  useBookerSummary,
  type BookerFilters,
  type BookerSummary,
} from "@/lib/booker-scorecard-api"

interface Props {
  filters: BookerFilters
  /** Baseline summary to diff against, supplied only by the Scenario tab. */
  baseline?: BookerSummary | null
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

/** Signed delta vs the baseline, e.g. "+$12,210" / "−4 orders". */
function delta(
  now: number | null | undefined,
  before: number | null | undefined,
  fmt: (v: number | null | undefined) => string,
): string | undefined {
  if (now === null || now === undefined) return undefined
  if (before === null || before === undefined) return undefined
  const d = now - before
  if (Math.abs(d) < 0.005) return "no change vs actual"
  return `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))} vs actual`
}

export function KpiCards({ filters, baseline }: Props) {
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
      : `${fmtCount(k.broken_threshold)} of ${fmtCount(k.threshold_orders)} with a threshold`

  // Cost Saving is the mirror of Broken Threshold: the same comparison, the
  // orders landing on the good side of it (Bruno R3).
  const savingSub =
    k?.cost_saving === null || k?.cost_saving === undefined
      ? "threshold source unavailable"
      : `over ${fmtCount(k.under_threshold)} orders under threshold`

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      <Card label="# Orders" value={fmtCount(k?.orders)} />
      <Card
        label="Profit"
        value={fmtUsd(k?.profit)}
        sub={baseline ? delta(k?.profit, baseline.profit, fmtUsd) : undefined}
      />
      <Card
        label="Margin %"
        value={fmtPct(k?.margin_pct)}
        sub={
          baseline
            ? delta(k?.margin_pct, baseline.margin_pct, (v) => fmtPct(v))
            : "Σ profit ÷ Σ revenue"
        }
      />
      <Card
        label="Avg Margin / Load"
        value={fmtUsd2(k?.avg_margin_per_load)}
        sub={
          baseline
            ? delta(k?.avg_margin_per_load, baseline.avg_margin_per_load, fmtUsd2)
            : "profit ÷ # orders"
        }
      />
      <Card
        label="Broken Threshold"
        // Bruno R4: the headline is the PERCENTAGE of comparable orders that
        // broke their threshold; the raw count moves to the sub-line.
        value={fmtPct(k?.broken_threshold_pct)}
        sub={brokenSub}
        tone={k?.broken_threshold ? "warn" : "default"}
        title="Share of orders whose Carrier Cost (Revenue − Profit) exceeds the threshold typed in Loads to Cover. Orders with no threshold are excluded from both the numerator and the denominator."
      />
      <Card
        label="Cost Saving"
        value={fmtUsd(k?.cost_saving)}
        sub={savingSub}
        title="Σ (threshold − Carrier Cost) across orders that came in UNDER their threshold. Orders at or above the threshold contribute nothing."
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
