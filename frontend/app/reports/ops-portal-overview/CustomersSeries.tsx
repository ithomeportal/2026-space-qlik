"use client"

// "Customers" measure of the KPI MANAGEMENT chart — Bruno PDF 2026-10-16 R1.
//
// One stacked bar per bucket: returning customers (light blue, the measure's
// usual bar colour) + NEW customers (emerald) — those with no load in the
// immediately previous day / week / month. Both are counts over the SAME
// population as the Vol. bars (total_charge IS NOT NULL AND <> 0, §96), from
// the same /combo scan. Budget, Losses, Projected and Forecast have no
// customer-count analogue and are hidden by Chart.tsx for this measure.

import { Bar, LabelList } from "recharts"
import { fmtCount } from "@/lib/ops-portal-overview-api"

export const NEW_CUSTOMER_COLOR = "#10B981"
const RETURNING_COLOR = "#7DD3FC"

/** Rendered as a Fragment of direct <Bar> children of the ComposedChart. */
export function renderCustomerBars() {
  return (
    <>
      <Bar dataKey="returning_customers" name="Returning" stackId="cust" fill={RETURNING_COLOR}>
        <LabelList
          dataKey="customers"
          position="insideTop"
          fontSize={9}
          fill="#1E3A5F"
          formatter={(v) => (Number(v) > 0 ? fmtCount(Number(v)) : "")}
        />
      </Bar>
      <Bar dataKey="new_customers" name="New" stackId="cust" fill={NEW_CUSTOMER_COLOR}>
        <LabelList
          dataKey="new_customers"
          position="top"
          fontSize={9}
          fill="#047857"
          formatter={(v) => (Number(v) > 0 ? `+${fmtCount(Number(v))}` : "")}
        />
      </Bar>
    </>
  )
}

export function CustomersTooltip({
  row,
  avg,
  showAvg,
}: {
  row: { label?: string; customers?: number | null; new_customers?: number | null }
  avg: number
  showAvg: boolean
}) {
  const total = Number(row.customers ?? 0)
  const fresh = Number(row.new_customers ?? 0)
  const items = [
    { label: "Customers", color: "#0EA5E9", value: total },
    { label: "New vs prev period", color: NEW_CUSTOMER_COLOR, value: fresh },
    { label: "Returning", color: RETURNING_COLOR, value: Math.max(0, total - fresh) },
    ...(showAvg ? [{ label: "Avg", color: "#9333EA", value: avg }] : []),
  ]
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-semibold text-[#111827]">{row.label}</div>
      {items.map((i) => (
        <div key={i.label} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: i.color }} />
            {i.label}
          </span>
          <span className="font-medium tabular-nums text-[#111827]">{fmtCount(i.value)}</span>
        </div>
      ))}
    </div>
  )
}
