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
// Attrition" measure. Bruno R13 (2026-07-01): the plotted value is now
// % Δ = (L8W − LW) / L8W = 1 − ratio, where LW = distinct customers this
// week (numerator) and L8W = distinct customers in the prior 8 weeks
// (denominator) — matching the Customer Attrition card's % Δ. This flips the
// earlier "ratio − 1" so a smaller current week reads as a positive delta.
// Data labels are always visible on each point, not just on hover.
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
        // Bruno R13: % Δ = (L8W − LW) / L8W = 1 − ratio (the raw ratio is
        // this-week ÷ prior-8-week distinct customers).
        pct: d.ratio === null || d.ratio === undefined ? null : 1 - d.ratio,
      })),
    [data],
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-1 text-base font-semibold text-[#1B3A5C]">
        Customer Attrition
      </div>
      <div className="mb-3 text-[11px] text-[#6B7280]">
        % Δ = (distinct customers in the prior 8 weeks − distinct customers this
        week) ÷ prior 8 weeks (last 15 weeks)
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
