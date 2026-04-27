"use client"

import { Loader2 } from "lucide-react"
import { useMemo, useState } from "react"
import {
  useAttritionPivot,
  type AttritionFilters,
  type PivotRow,
} from "@/lib/attrition-wow-api"
import { AttritionErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd } from "../format"

interface Props {
  filters: AttritionFilters
}

type Metric = "loads" | "revenue" | "profit" | "margin"
type Dim = "customer" | "team"

const METRICS: { key: Metric; label: string; fmt: (v: number | null | undefined) => string }[] = [
  { key: "loads",   label: "# Loads",    fmt: fmtCount },
  { key: "revenue", label: "$ Revenue",  fmt: fmtUsd },
  { key: "profit",  label: "$ Profit",   fmt: fmtUsd },
  { key: "margin",  label: "% Margin",   fmt: fmtPct },
]

const DIMS: { key: Dim; label: string }[] = [
  { key: "team",     label: "by Team" },
  { key: "customer", label: "by Customer" },
]

export function PivotsTab({ filters }: Props) {
  const [metric, setMetric] = useState<Metric>("loads")
  const [dim, setDim] = useState<Dim>("team")
  const [weeks] = useState<number>(12)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#E5E7EB] bg-white px-4 py-3 text-xs shadow-sm">
        <div className="flex items-center gap-1">
          <span className="font-semibold uppercase tracking-wider text-[#6B7280]">
            Metric
          </span>
          <div className="ml-1 flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB]">
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                className={`px-3 py-1.5 ${
                  metric === m.key
                    ? "rounded-md bg-white font-semibold text-[#1B3A5C] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <span className="font-semibold uppercase tracking-wider text-[#6B7280]">
            View
          </span>
          <div className="ml-1 flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB]">
            {DIMS.map((d) => (
              <button
                key={d.key}
                onClick={() => setDim(d.key)}
                className={`px-3 py-1.5 ${
                  dim === d.key
                    ? "rounded-md bg-white font-semibold text-[#1B3A5C] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
        <div className="ml-auto text-[10px] text-[#6B7280]">
          Cells colored vs each row&apos;s 8-week average · current week excluded
        </div>
      </div>

      <PivotPanel filters={filters} dim={dim} metric={metric} weeks={weeks} />
    </div>
  )
}

function PivotPanel({
  filters,
  dim,
  metric,
  weeks,
}: {
  filters: AttritionFilters
  dim: Dim
  metric: Metric
  weeks: number
}) {
  const { data: res, isLoading, error } = useAttritionPivot(
    filters,
    dim,
    metric,
    weeks,
  )
  const rows = res?.data ?? []
  const fmt = METRICS.find((m) => m.key === metric)!.fmt

  // Build wide pivot: weeks (cols, latest first) × dim_keys (rows)
  const { weeksList, pivot } = useMemo(() => {
    const weekSet = new Set<string>()
    const byKey = new Map<string, Map<string, number | null>>()
    for (const r of rows as PivotRow[]) {
      weekSet.add(r.week_start)
      if (!byKey.has(r.dim_key)) byKey.set(r.dim_key, new Map())
      byKey.get(r.dim_key)!.set(r.week_start, r.value)
    }
    const weeksList = Array.from(weekSet).sort().reverse() // latest first
    const pivotEntries = Array.from(byKey.entries()).map(([k, weekMap]) => {
      const values = weeksList.map((w) => weekMap.get(w) ?? null)
      // 8-week ref: avg of the 8 most-recent NON-NULL completed weeks per row
      const ref = (() => {
        const nonNull = values.filter((v): v is number => v !== null)
        if (nonNull.length === 0) return null
        const slice = nonNull.slice(0, 8)
        return slice.reduce((a, b) => a + b, 0) / slice.length
      })()
      const total = values.reduce<number>((a, b) => a + (b ?? 0), 0)
      return { dim_key: k, values, ref, total }
    })
    pivotEntries.sort((a, b) => (b.total ?? 0) - (a.total ?? 0))
    return { weeksList, pivot: pivotEntries }
  }, [rows])

  if (isLoading && pivot.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <AttritionErrorBanner errors={[error]} label="Pivot" />
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="bg-[#F9FAFB] text-[10px] uppercase tracking-wider text-[#6B7280]">
            <tr>
              <th className="sticky left-0 z-10 bg-[#F9FAFB] px-3 py-2 text-left">
                {dim === "team" ? "Team" : "Customer"}
              </th>
              <th className="bg-[#F9FAFB] px-3 py-2 text-right text-[#1B3A5C]">
                8-week avg
              </th>
              {weeksList.map((w) => (
                <th key={w} className="px-3 py-2 text-right">
                  {fmtMonDay(w)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {pivot.map((row) => (
              <tr key={row.dim_key} className="hover:bg-[#FAFAFA]">
                <td
                  className="sticky left-0 z-10 max-w-[260px] truncate bg-white px-3 py-1.5 text-[#111827]"
                  title={row.dim_key}
                >
                  {dim === "customer" && (
                    <StatusDot
                      lw={row.values[0] ?? null}
                      l2w={row.values[1] ?? null}
                      ref={row.ref}
                    />
                  )}
                  {row.dim_key}
                </td>
                <td className="bg-white px-3 py-1.5 text-right font-mono font-semibold text-[#1B3A5C]">
                  {row.ref === null ? "—" : fmt(row.ref)}
                </td>
                {row.values.map((v, i) => (
                  <td
                    key={i}
                    className={`px-3 py-1.5 text-right font-mono ${cellShade(v, row.ref)}`}
                  >
                    {v === null ? "—" : fmt(v)}
                  </td>
                ))}
              </tr>
            ))}
            {pivot.length === 0 && (
              <tr>
                <td colSpan={weeksList.length + 2} className="py-8 text-center text-xs text-[#9CA3AF]">
                  No data in scope.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function cellShade(v: number | null, ref: number | null): string {
  if (v === null || ref === null) return "text-[#9CA3AF]"
  // Treat 0 as below-average for non-zero ref (Bruno's coloring rule).
  if (v > ref) return "bg-[#DCFCE7] text-[#15803D]"
  if (v < ref) return "bg-[#FEE2E2] text-[#DC2626]"
  return "text-[#374151]"
}

function fmtMonDay(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00")
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  } catch {
    return iso
  }
}

// Bruno's "Just in by Customer" rule (2026-04-27):
//   both LW & L2W >= 8-week avg  → green
//   one of LW or L2W <  8-week avg → yellow
//   both LW & L2W <  8-week avg  → red
function StatusDot({
  lw,
  l2w,
  ref,
}: {
  lw: number | null
  l2w: number | null
  ref: number | null
}) {
  if (ref === null || lw === null || l2w === null) {
    return (
      <span
        className="mr-2 inline-block h-2 w-2 rounded-full bg-[#D1D5DB]"
        title="Insufficient data"
      />
    )
  }
  const lwBelow = lw < ref
  const l2wBelow = l2w < ref
  let color = "#15803D" // green: both at or above
  let label = "Both LW & L2W ≥ 8-week avg"
  if (lwBelow && l2wBelow) {
    color = "#DC2626"
    label = "Both LW & L2W below 8-week avg"
  } else if (lwBelow || l2wBelow) {
    color = "#CA8A04"
    label = "LW or L2W below 8-week avg"
  }
  return (
    <span
      className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
      style={{ backgroundColor: color }}
      title={label}
    />
  )
}
