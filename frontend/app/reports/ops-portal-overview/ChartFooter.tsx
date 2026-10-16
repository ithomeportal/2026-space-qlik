"use client"

// Footer of the KPI MANAGEMENT chart: working-day boxes + the Profit-TM gauge.
// Extracted from Chart.tsx (Bruno PDF 2026-10-16 R1) to keep that file under
// the size cap while the chart gained Customers + Projected candles.

import { fmtUsd, fmtUsdSigned } from "@/lib/ops-portal-overview-api"

export function KpiBox({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "neutral" | "accent"
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        tone === "accent"
          ? "border-[#BFDBFE] bg-[#EFF6FF]"
          : "border-[#E5E7EB] bg-white"
      }`}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className="text-2xl font-bold text-[#1B3A5C]">{value}</div>
    </div>
  )
}

/** Bruno (PDF 2026-08-31) R2: "Target" → "Budget", and the readout becomes
 *  Actual / Budget / Differential / Projected Profit.
 *
 *  ⚠ Actual is month-to-DATE while Budget is the WHOLE month (§92 — a
 *  whole-period plan must not be truncated to today). So Differential reads
 *  negative for most of the month BY CONSTRUCTION and is not a warning sign;
 *  Projected Profit is the leg to compare against Budget. The labels are spelt
 *  out rather than implied so nobody reads the gap as underperformance.
 */
export function ProfitTmGauge({
  mtd,
  budget,
  projProfit,
}: {
  mtd: number
  budget: number
  projProfit: number
}) {
  const max = Math.max(budget, mtd, 1) * 1.05
  const pct = Math.min(100, Math.max(0, (mtd / max) * 100))
  const budgetPct = budget > 0 ? Math.min(100, Math.max(0, (budget / max) * 100)) : 0
  const completionPct = budget > 0 ? (mtd / budget) * 100 : 0
  const onTrack = budget > 0 && mtd >= budget * (new Date().getDate() / 30)
  const differential = mtd - budget
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
          Profit - TM
        </span>
        <span className="text-xs font-semibold tabular-nums text-[#1B3A5C]">
          <span title="Month-to-date profit">Actual {fmtUsd(mtd)}</span>
          <span className="text-[#D1D5DB]"> / </span>
          <span className="text-[#6B7280]" title="Whole-month budget">
            Budget {fmtUsd(budget)}
          </span>
          <span className="text-[#D1D5DB]"> / </span>
          <span
            className={differential < 0 ? "text-[#DC2626]" : "text-[#15803D]"}
            title="Actual − Budget. Actual is month-to-date and Budget is the whole month, so this is negative for most of the month by construction — compare Projected Profit against Budget instead."
          >
            Differential {fmtUsdSigned(differential)}
          </span>
          <span className="text-[#D1D5DB]"> / </span>
          <span
            className={projProfit < 0 ? "text-[#DC2626]" : "text-[#1B3A5C]"}
            title="End-of-month projection — the same number the Monthly Projection panel shows"
          >
            Projected Profit {fmtUsd(projProfit)}
          </span>
        </span>
      </div>
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-[#F3F4F6]">
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${pct}%`,
            background: onTrack ? "#16A34A" : mtd < 0 ? "#DC2626" : "#F59E0B",
          }}
        />
        {budgetPct > 0 && (
          <div
            className="absolute inset-y-0 w-0.5 bg-[#1B3A5C]"
            style={{ left: `${budgetPct}%` }}
          />
        )}
      </div>
      {budget > 0 && (
        <div className="mt-0.5 text-center text-xs font-medium tabular-nums text-[#374151]">
          {completionPct.toFixed(2)}%
        </div>
      )}
    </div>
  )
}
