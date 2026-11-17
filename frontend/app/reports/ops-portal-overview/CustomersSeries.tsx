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

// Bruno PDF 2026-11-17 R1: each segment shows its OWN count — Returning inside
// the blue, "+N" New inside the green — and the Customers total sits on top of
// the stack in bold, larger. (Before, the blue segment printed the TOTAL, which
// read as the returning count.)
//
// ⚠ Recharts 3 drops a zero-height bar rectangle AND its label (Bar.js: "Filter
// out 0-dimension rectangles"), so a total label hung on the New bar vanished
// in every bucket with no new customer. A custom `shape` opts the bar out of
// that filter, so the stack-top label always renders.
const LABEL_SEP = "|"
const MIN_INSIDE_PX = 11

function NewSegmentShape(props: unknown) {
  const { x, y, width, height } = props as { x?: number; y?: number; width?: number; height?: number }
  if (x == null || y == null || !width || !height || height <= 0) return <g />
  return <rect x={x} y={y} width={width} height={height} fill={NEW_CUSTOMER_COLOR} />
}

function stackLabelValue(entry: unknown): string {
  const p = (entry as { payload?: { customers?: number | null; new_customers?: number | null } }).payload
  return `${Number(p?.customers ?? 0)}${LABEL_SEP}${Number(p?.new_customers ?? 0)}`
}

/** Bold total above the stack + "+N" inside the green (or beside the total
 *  when the green is too thin to hold text). */
function StackTopLabel(props: unknown) {
  const { viewBox, value } = props as {
    viewBox?: { x?: number; y?: number; width?: number; height?: number }
    value?: string | number
  }
  const [total, fresh] = String(value ?? "").split(LABEL_SEP).map(Number)
  if (!viewBox || viewBox.x == null || viewBox.y == null || !(total > 0)) return null
  const cx = viewBox.x + (viewBox.width ?? 0) / 2
  const h = viewBox.height ?? 0
  const inside = fresh > 0 && h >= MIN_INSIDE_PX
  const beside = fresh > 0 && !inside
  return (
    <g>
      <text x={cx} y={viewBox.y - 5} textAnchor="middle" fontSize={12} fontWeight={700} fill="#0F172A">
        {fmtCount(total)}
        {beside && (
          <tspan fontSize={9} fontWeight={600} fill="#047857">{` +${fmtCount(fresh)}`}</tspan>
        )}
      </text>
      {inside && (
        <text x={cx} y={viewBox.y + h / 2} dy={3} textAnchor="middle" fontSize={9} fontWeight={600} fill="#064E3B">
          {`+${fmtCount(fresh)}`}
        </text>
      )}
    </g>
  )
}

/** Rendered as a Fragment of direct <Bar> children of the ComposedChart. */
export function renderCustomerBars() {
  return (
    <>
      <Bar dataKey="returning_customers" name="Returning" stackId="cust" fill={RETURNING_COLOR}>
        <LabelList
          dataKey="returning_customers"
          position="insideTop"
          fontSize={9}
          fill="#1E3A5F"
          formatter={(v) => (Number(v) > 0 ? fmtCount(Number(v)) : "")}
        />
      </Bar>
      <Bar dataKey="new_customers" name="New" stackId="cust" fill={NEW_CUSTOMER_COLOR} shape={NewSegmentShape}>
        <LabelList valueAccessor={stackLabelValue} content={StackTopLabel} />
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
