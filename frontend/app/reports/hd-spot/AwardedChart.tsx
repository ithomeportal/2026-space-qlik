"use client"

import { useMemo } from "react"
import { Loader2 } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { useHdSpotChart, fmtDate, type HdSpotFilters } from "@/lib/hd-spot-api"

/** Awarded (bars) + Conversion Ratio (line, right axis), by day.
 *
 *  Request 4: data labels on, follows the Date filter, daily grain.
 */
export function AwardedChart({ filters }: { filters: HdSpotFilters }) {
  const { data, isLoading, error } = useHdSpotChart(filters)

  const rows = useMemo(() => {
    // Percentages travel as fractions; scale to display units BEFORE render so
    // the axis, the tooltip and the line all agree.
    return (data?.data ?? []).map((p) => ({
      date: p.date,
      label: fmtDate(p.date),
      awarded: p.awarded,
      conversion: p.conversion === null ? null : p.conversion * 100,
    }))
  }, [data])

  // Auto-scale the conversion axis to the data. A fixed 0–100 squashes the line
  // onto the x-axis: real HD conversion runs ~3–5% on VAN and up to ~45% on
  // FLATBED. `ceil(max) + 2` leaves label room above the peak.
  const y1Max = useMemo(() => {
    const max = Math.max(0, ...rows.map((r) => Number(r.conversion) || 0))
    return Math.ceil(max) + 2
  }, [rows])

  if (error) {
    return (
      <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
        Could not load the chart: {error instanceof Error ? error.message : "unknown error"}
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-[#1B3A5C]">
          Awarded &amp; Conversion Ratio
        </h2>
        <span className="text-[10px] text-[#9CA3AF]">
          by day · follows the date filter
        </span>
      </div>

      {isLoading && rows.length === 0 ? (
        <div className="flex h-[280px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-[280px] items-center justify-center text-xs text-[#6B7280]">
          No spot activity in this window.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={rows} margin={{ top: 18, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} allowDecimals={false} />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, y1Max]}
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              formatter={(value, name) => {
                if (value === null || value === undefined) return ["—", name]
                if (name === "Awarded")
                  return [Number(value).toLocaleString("en-US"), name]
                return [`${Number(value).toFixed(1)}%`, name]
              }}
              labelFormatter={(v) => `Day ${v}`}
            />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Bar
              yAxisId="left"
              dataKey="awarded"
              name="Awarded"
              fill="#93C5FD"
              radius={[3, 3, 0, 0]}
            >
              {/* Data labels (Request 4). Zero days return null so the label is
                  hidden rather than printing a row of 0s. */}
              <LabelList
                dataKey="awarded"
                position="top"
                style={{ fontSize: 9, fill: "#1D4ED8" }}
                formatter={(v) => {
                  const n = Number(v)
                  return v === null || v === undefined || !n
                    ? null
                    : n.toLocaleString("en-US")
                }}
              />
            </Bar>
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="conversion"
              name="Conversion Ratio"
              stroke="#DC2626"
              strokeWidth={2}
              dot={{ r: 2 }}
              connectNulls
            >
              {/* Anchored BELOW the line: conversion = awarded/quoted traces the
                  bar tops, so labels above would overprint the bar labels. */}
              <LabelList
                dataKey="conversion"
                position="bottom"
                style={{ fontSize: 9, fill: "#DC2626" }}
                formatter={(v) => {
                  const n = Number(v)
                  return v === null || v === undefined || !n ? null : `${n.toFixed(1)}%`
                }}
              />
            </Line>
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
