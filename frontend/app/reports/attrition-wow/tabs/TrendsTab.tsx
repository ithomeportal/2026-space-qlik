"use client"

import { Loader2 } from "lucide-react"
import { useMemo } from "react"
import {
  useAttritionTrends,
  type AttritionFilters,
  type WeekRow,
} from "@/lib/attrition-wow-api"
import { AttritionErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd } from "../format"

interface Props {
  filters: AttritionFilters
}

type Field = "loads" | "customers" | "revenue" | "profit" | "margin_pct"

const FIELDS: {
  key: Field
  title: string
  fmt: (v: number | null | undefined) => string
  color: string  // bar fill
  axisColor: string
  isPct?: boolean
}[] = [
  { key: "loads",      title: "# Loads by Week",     fmt: fmtCount, color: "#DC2626", axisColor: "#DC2626" },
  { key: "customers",  title: "# Customers by Week", fmt: fmtCount, color: "#0891B2", axisColor: "#0891B2" },
  { key: "revenue",    title: "$ Revenue by Week",   fmt: fmtUsd,   color: "#0E7490", axisColor: "#0E7490" },
  { key: "profit",     title: "$ Profit by Week",    fmt: fmtUsd,   color: "#CA8A04", axisColor: "#CA8A04" },
  { key: "margin_pct", title: "% Margin by Week",    fmt: fmtPct,   color: "#7C3AED", axisColor: "#7C3AED", isPct: true },
]

export function TrendsTab({ filters }: Props) {
  const { data: res, isLoading, error } = useAttritionTrends(filters, 15)
  const data = res?.data
  const weeks = data?.weeks ?? []
  const ref = data?.reference

  return (
    <div className="space-y-4">
      <AttritionErrorBanner errors={[error]} label="Weekly Trends" />

      {isLoading && weeks.length === 0 ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {FIELDS.map((f) => (
            <BarPanel
              key={f.key}
              title={f.title}
              data={weeks}
              field={f.key}
              fmt={f.fmt}
              color={f.color}
              axisColor={f.axisColor}
              isPct={f.isPct ?? false}
              ref={
                f.key === "loads"
                  ? ref?.l8w_avg_loads ?? null
                  : f.key === "customers"
                    ? ref?.l8w_avg_customers ?? null
                    : f.key === "revenue"
                      ? ref?.l8w_avg_revenue ?? null
                      : f.key === "profit"
                        ? ref?.l8w_avg_profit ?? null
                        : ref?.l8w_avg_margin ?? null
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function BarPanel({
  title,
  data,
  field,
  fmt,
  color,
  axisColor,
  isPct,
  ref,
}: {
  title: string
  data: WeekRow[]
  field: Field
  fmt: (v: number | null | undefined) => string
  color: string
  axisColor: string
  isPct: boolean
  ref: number | null
}) {
  const values = useMemo(
    () =>
      data.map((d) => {
        const raw = d[field]
        return typeof raw === "number" ? raw : 0
      }),
    [data, field],
  )
  const max = Math.max(0, ...values, ref ?? 0)
  const safeMax = max === 0 ? 1 : max

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold" style={{ color: axisColor }}>
          {title}
        </div>
        {ref !== null && (
          <div className="text-[10px] text-[#6B7280]">
            <span className="font-semibold" style={{ color: axisColor }}>
              ━━
            </span>{" "}
            8w avg: {fmt(ref)}
          </div>
        )}
      </div>
      <div
        className="mt-3 grid gap-1"
        style={{
          minHeight: 200,
          gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))`,
        }}
      >
        {data.map((d, i) => {
          const v = values[i]
          const h = (Math.abs(v) / safeMax) * 180
          return (
            <div
              key={d.week_start}
              className="flex flex-col items-center justify-end"
              style={{ height: 200 }}
              title={`${d.week_start}: ${fmt(v)}`}
            >
              <div className="text-[8px] font-mono text-[#374151]">
                {compact(v, isPct)}
              </div>
              <div
                className="w-full rounded-t"
                style={{
                  height: `${h}px`,
                  backgroundColor: v < 0 ? "#DC2626" : color,
                  opacity: v === 0 ? 0.2 : 1,
                }}
              />
            </div>
          )
        })}
      </div>
      <div
        className="mt-1 grid gap-1 text-[8px] text-[#6B7280]"
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
