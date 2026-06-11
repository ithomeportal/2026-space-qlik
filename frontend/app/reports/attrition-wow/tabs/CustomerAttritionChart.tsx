"use client"

import { useMemo } from "react"
import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { CustomerAttritionPoint } from "@/lib/attrition-wow-api"
import { fmtPct } from "../format"

// Bruno 2026-06-11 (Overview): a 15-week line of the weekly "Customer
// Attrition" measure. R1 (PDF round 2): the plotted value is the ratio
// MINUS 1 — i.e. (distinct customers this week / distinct customers in the
// prior 8 weeks) − 1 — so the line reads as a true attrition delta (always
// negative: this week is a fraction of the larger 8-week pool). R2: data
// labels are always visible on each point, not just on hover.
// X-axis = ISO week number; Y-axis = %.
// Recharts v3 types formatters loosely — keep callbacks unannotated and
// coerce with Number() so `next build` stays green (SPEC note: v3 strict
// formatter typing).
export function CustomerAttritionChart({
  data,
}: {
  data: CustomerAttritionPoint[]
}) {
  const rows = useMemo(
    () =>
      data.map((d) => ({
        ...d,
        label: `W${d.week_no}`,
        // Bruno R1: plot ratio − 1 (the attrition delta), not the raw ratio.
        pct: d.ratio === null || d.ratio === undefined ? null : d.ratio - 1,
      })),
    [data],
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-1 text-base font-semibold text-[#1B3A5C]">
        Customer Attrition
      </div>
      <div className="mb-3 text-[11px] text-[#6B7280]">
        (Distinct customers each week ÷ distinct customers in the prior 8 weeks)
        − 1 (last 15 weeks)
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 22, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis
            tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`}
            tick={{ fontSize: 11 }}
            width={48}
          />
          <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="2 2" />
          <Tooltip
            labelFormatter={(label, payload) => {
              const p = payload && payload[0] ? payload[0].payload : null
              return p
                ? `${label} (${p.numerator} / ${p.denominator})`
                : String(label)
            }}
            formatter={(v) => [fmtPct(Number(v)), "Attrition"]}
          />
          <Line
            type="monotone"
            dataKey="pct"
            name="Attrition"
            stroke="#1B3A5C"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls
          >
            <LabelList
              dataKey="pct"
              position="top"
              offset={10}
              fontSize={10}
              fill="#1B3A5C"
              formatter={(v) =>
                v === null || v === undefined ? "" : fmtPct(Number(v))
              }
            />
          </Line>
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
