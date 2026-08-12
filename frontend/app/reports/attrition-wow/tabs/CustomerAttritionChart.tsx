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
// Bruno 2026-08-05 (R18): the plotted value was the RAW ratio —
//   LW ÷ L8W = distinct customers this week ÷ avg weekly customers in the
//   prior 8 weeks
// — so that the last point equalled the Customer Attrition card above the
// chart (card LW 31 / L8W 35.4 → 87.6%). That denominator work STANDS.
//
// Bruno 2026-08-12 (R19): the plotted value is `1 − ratio` again, per his
// worked examples — W32 `1 − (37 / 34.9) = −6.09%`, W31 `1 − (31 / 35.4) =
// 12.43%`. FOURTH flip in this family: R11 `ratio − 1` → R13 `1 − ratio` →
// R18 `ratio` → R19 `1 − ratio`. History kept in place, not deleted (SPEC:
// Bruno rounds reverse earlier decisions — keep the plumbing).
//
// Only the PLOTTED quantity changed; `/customer-attrition` is untouched and
// still ships `ratio` / `numerator` / `denominator`, so the tooltip's
// "37 / 34.9" breakdown is unaffected.
//
// The upside of this flip: `1 − LW/L8W` == `(L8W − LW)/L8W`, which is exactly
// the Customer Attrition CARD's `% Δ` cell. Card and chart are now the SAME
// number, not complements (R18 left them at 12.37% vs 87.63%).
//
// ⚠ Meaning + scale changed again. Values sit AROUND 0%, not 100%, and the
// SIGN carries the message: POSITIVE = fewer active customers than the 8-week
// average = attrition UP (the card colours that red); negative = more
// customers than usual. Hence the dashed baseline at 0, not 1, and a domain
// that must span negatives. Subtitle states the formula so nobody reads
// −6.09% as "6% of customers churned".
//
// Data labels are always visible on each point, not just on hover.
// X-axis = ISO week number; Y-axis = %.
// Recharts v3 types formatters loosely — keep callbacks unannotated and
// coerce with Number() so `next build` stays green (SPEC note: v3 strict
// formatter typing).
export function CustomerAttritionChart({
  data,
  singleCustomer = false,
}: {
  data: CustomerAttritionPoint[]
  /** True when the report is filtered to ONE customer — see below. */
  singleCustomer?: boolean
}) {
  const rows = useMemo(
    () =>
      data.map((d) => ({
        ...d,
        label: `W${d.week_no}`,
        // Bruno 2026-08-12 (R19): plot 1 − ratio, i.e. 1 − (this week ÷
        // prior-8-week weekly average). NOT the raw ratio (R18) and NOT
        // ratio − 1 (R11) — the sign matters, see the header comment.
        pct: d.ratio === null || d.ratio === undefined ? null : 1 - d.ratio,
      })),
    [data],
  )

  // Explicit domain, snapped to 5% steps so the ticks stay round, with
  // headroom above the peak so the top data label clears the plot area (same
  // fix as the digest charts, 417447c — Recharts' auto domain stops exactly at
  // the peak and clips the label).
  //
  // Bruno 2026-08-12 (R19): the series now straddles 0 (roughly −11%…+15%),
  // so the old `[0, yMax]` would push every negative week off the bottom of
  // the chart. Seed the reduce with 0 on BOTH ends: that forces the domain to
  // contain the baseline, and Recharts defaults ReferenceLine to
  // ifOverflow="discard", so a domain that missed 0 would SILENTLY drop the
  // baseline — the one line that tells the reader which side of the 8-week
  // average this week landed on.
  const [yMin, yMax] = useMemo(() => {
    const vals = rows
      .map((r) => r.pct)
      .filter((v): v is number => v !== null && v !== undefined)
    const lo = vals.reduce((m, v) => (v < m ? v : m), 0)
    const hi = vals.reduce((m, v) => (v > m ? v : m), 0)
    // At least ±2.5pp of pad so a flat series still gets a readable band.
    const pad = Math.max((hi - lo) * 0.15, 0.025)
    return [
      Math.floor((lo - pad) * 20) / 20,
      Math.ceil((hi + pad) * 20) / 20,
    ] as const
  }, [rows])

  // Under a single-customer filter this measure stops meaning what its title
  // says. The numerator collapses to 0 or 1 and the denominator to (active
  // weeks)/8, so the ratio becomes 8/(active weeks) — a lumpy step function
  // reading ±100%, ±700% and so on. It is describing how OFTEN that one
  // customer ships, not attrition of a customer base, and a −700% spike reads
  // as a broken chart. Suppress the line and say why, rather than render a
  // number nobody should act on. (The card above has the same property by
  // construction since R17 — the union denominator used to mask it by pinning
  // this view at a clean 100%.)
  if (singleCustomer) {
    return (
      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-1 text-base font-semibold text-[#1B3A5C]">
          Customer Attrition
        </div>
        <div className="flex h-[180px] items-center justify-center px-6">
          <p className="max-w-md text-center text-[12px] leading-relaxed text-[#6B7280]">
            Not shown for a single customer. This measure compares how many
            distinct customers shipped this week against the weekly average of
            the prior 8 weeks — with one customer selected it can only be 0 or
            1 over that average, so it reports shipping frequency, not
            attrition. Clear the customer filter to see the trend, or use{" "}
            <span className="font-medium text-[#374151]">Weekly Loads</span> above
            for this customer&apos;s own cadence.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-1 text-base font-semibold text-[#1B3A5C]">
        Customer Attrition
      </div>
      <div className="mb-3 text-[11px] text-[#6B7280]">
        % = 1 − (distinct customers this week ÷ average weekly customers over
        the prior 8 weeks), last 15 weeks. 0% = matched the 8-week average;
        positive = fewer customers than usual (attrition up).
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 22, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis
            domain={[yMin, yMax]}
            tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`}
            tick={{ fontSize: 11 }}
            width={48}
          />
          {/* 0% = this week matched the prior-8-week weekly average. */}
          <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="2 2" />
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
