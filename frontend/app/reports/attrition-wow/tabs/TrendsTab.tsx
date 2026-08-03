"use client"

import { Loader2 } from "lucide-react"
import {
  useAttritionTrends,
  type AttritionFilters,
} from "@/lib/attrition-wow-api"
import { AttritionErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtCount1, fmtPct, fmtUsd } from "../format"
import { BarPanel, type BarField } from "./BarPanel"

interface Props {
  filters: AttritionFilters
}

const FIELDS: {
  key: BarField
  title: string
  fmt: (v: number | null | undefined) => string
  color: string
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
              refValue={
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
              /* The count panels' reference line is a per-week AVERAGE and is
                 usually fractional — render it to 1 decimal so it reads the
                 same as the Overview attrition cards' L8W (Bruno 2026-08-03).
                 Money/% panels keep their own formatter. */
              refFmt={
                f.key === "loads" || f.key === "customers" ? fmtCount1 : undefined
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
