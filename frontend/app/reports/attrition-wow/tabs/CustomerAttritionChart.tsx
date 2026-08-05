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
import { fmtCount1, fmtPct } from "../format"

// Bruno 2026-06-11 (Overview): a 15-week line of the weekly "Customer
// Attrition" measure.
//
// Bruno 2026-08-05: the plotted value is the RAW ratio again —
//   LW ÷ L8W = distinct customers this week ÷ avg weekly customers in the
//   prior 8 weeks
// — which REVERSES R13's "% Δ = 1 − ratio". The requirement is that the last
// point equal the Customer Attrition card directly above the chart: the card
// reads LW 31 and L8W 35.4, so the chart must read 31 / 35.4 ≈ 87.6%. Under
// R13 (and a union-distinct denominator of 55) it read 43.64% instead.
// Values now sit AROUND 100%: 100% = this week matched the 8-week weekly
// average, below = fewer active customers than usual. Hence the dashed
// baseline at 1, not 0.
//
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
        // Bruno 2026-08-05: plot the ratio itself (this week ÷ prior-8-week
        // weekly average), NOT 1 − ratio.
        pct: d.ratio === null || d.ratio === undefined ? null : d.ratio,
      })),
    [data],
  )

  // Headroom so the top data label clears the plot area (same fix as the
  // digest charts, 417447c). Ratios now peak well above 100%, and Recharts'
  // auto domain stops exactly at the peak, clipping its label. Snap up to the
  // next 5% so the ticks stay round.
  //
  // Floor at 105%: Recharts defaults ReferenceLine to ifOverflow="discard", so
  // a domain topping out below 1 would SILENTLY drop the 100% baseline —
  // exactly in the scope (a shrinking team, every week in the 70-84% band)
  // where the reader most needs to see that the line is under target.
  const yMax = useMemo(() => {
    const peak = rows.reduce(
      (m, r) => (r.pct !== null && r.pct > m ? r.pct : m),
      0,
    )
    return Math.max(1.05, Math.ceil(peak * 1.12 * 20) / 20)
  }, [rows])

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-1 text-base font-semibold text-[#1B3A5C]">
        Customer Attrition
      </div>
      <div className="mb-3 text-[11px] text-[#6B7280]">
        % = distinct customers this week ÷ average weekly customers over the
        prior 8 weeks (last 15 weeks). 100% = matched the 8-week average.
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 22, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis
            domain={[0, yMax]}
            tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`}
            tick={{ fontSize: 11 }}
            width={48}
          />
          {/* 100% = this week matched the prior-8-week weekly average. */}
          <ReferenceLine y={1} stroke="#9CA3AF" strokeDasharray="2 2" />
          <Tooltip
            labelFormatter={(label, payload) => {
              const p = payload && payload[0] ? payload[0].payload : null
              // Denominator is an average (35.375), so show it the way the
              // Customer Attrition card does — 1 decimal.
              return p
                ? `${label} (${p.numerator} / ${fmtCount1(p.denominator)})`
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
