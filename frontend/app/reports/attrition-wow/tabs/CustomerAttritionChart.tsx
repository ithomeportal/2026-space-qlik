"use client"

import { useMemo } from "react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { CustomerAttritionPoint } from "@/lib/attrition-wow-api"
import { fmtPct } from "../format"

// Bruno 2026-06-11 (Overview, Request 1): a 15-week line of the weekly
// "Customer Attrition" ratio (distinct customers this week / distinct
// customers in the prior 8 weeks). X-axis = ISO week number; Y-axis = %.
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
        pct: d.ratio,
      })),
    [data],
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-1 text-base font-semibold text-[#1B3A5C]">
        Customer Attrition
      </div>
      <div className="mb-3 text-[11px] text-[#6B7280]">
        Distinct customers each week ÷ distinct customers in the prior 8 weeks
        (last 15 weeks)
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis
            tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`}
            tick={{ fontSize: 11 }}
            width={48}
          />
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
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
