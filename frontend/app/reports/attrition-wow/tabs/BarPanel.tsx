"use client"

import { useMemo } from "react"
import type { WeekRow } from "@/lib/attrition-wow-api"

export type BarField = "loads" | "customers" | "revenue" | "profit" | "margin_pct"

// Shared bar-chart panel — used by Trends tab AND duplicated on Overview tab
// (Bruno round-3, 2026-05-07: "duplicate # Loads by Week and # Customers by
// Week below the table"). Bars at-or-above the 8w avg use the panel color;
// bars below drop to gray so the user picks up dips at a glance.
export function BarPanel({
  title,
  data,
  field,
  fmt,
  color,
  axisColor,
  isPct,
  refValue,
  height = 200,
  showLegend = true,
}: {
  title: string
  data: WeekRow[]
  field: BarField
  fmt: (v: number | null | undefined) => string
  color: string
  axisColor: string
  isPct: boolean
  refValue: number | null
  height?: number
  showLegend?: boolean
}) {
  const values = useMemo(
    () =>
      data.map((d) => {
        const raw = d[field]
        return typeof raw === "number" ? raw : 0
      }),
    [data, field],
  )
  const max = Math.max(0, ...values, refValue ?? 0)
  const safeMax = max === 0 ? 1 : max
  const barAreaPx = Math.max(120, height - 20)

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-base font-semibold" style={{ color: axisColor }}>
          {title}
        </div>
        {refValue !== null && (
          <div className="text-xs text-[#374151]">
            <span className="font-semibold" style={{ color: axisColor }}>
              ━━
            </span>{" "}
            8w avg: <span className="font-semibold">{fmt(refValue)}</span>
          </div>
        )}
      </div>
      <div
        className="mt-3 grid gap-1"
        style={{
          minHeight: height,
          gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))`,
        }}
      >
        {data.map((d, i) => {
          const v = values[i]
          const h = (Math.abs(v) / safeMax) * (barAreaPx - 20)
          const aboveAvg = refValue !== null && v >= refValue
          const fill = v < 0 ? "#DC2626" : aboveAvg ? color : "#D1D5DB"
          return (
            <div
              key={d.week_start}
              className="flex flex-col items-center justify-end"
              style={{ height: barAreaPx }}
              title={`${d.week_start}: ${fmt(v)}`}
            >
              <div className="text-[10px] font-mono text-[#374151]">
                {compact(v, isPct)}
              </div>
              <div
                className="w-full rounded-t"
                style={{
                  height: `${h}px`,
                  backgroundColor: fill,
                  opacity: v === 0 ? 0.2 : 1,
                }}
              />
            </div>
          )
        })}
      </div>
      <div
        className="mt-1 grid gap-1 text-[10px] text-[#6B7280]"
        style={{
          gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))`,
        }}
      >
        {data.map((d) => (
          <div key={d.week_start} className="truncate text-center">
            {weekLabel(d.week_start)}
          </div>
        ))}
      </div>
      {showLegend && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-[#374151]">
          <span className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ backgroundColor: color }}
            />
            <span>≥ 8w avg</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#D1D5DB]" />
            <span>below 8w avg</span>
          </span>
        </div>
      )}
    </div>
  )
}

function compact(v: number | null, isPct: boolean): string {
  if (v === null || v === undefined) return ""
  if (isPct) return `${(v * 100).toFixed(1)}%`
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}k`
  return Math.round(v).toString()
}

function weekLabel(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00")
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  } catch {
    return iso
  }
}
