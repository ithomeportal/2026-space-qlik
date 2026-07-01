"use client"

import { useEffect, useRef } from "react"
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
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtWeekRange,
  useCeoWeekly,
  type CeoFilters,
} from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"

// Bruno R7 (2026-05-26): explicit per-series colors.
const C_LOADS = "rgb(191, 0, 0)"
const C_REVENUE = "rgb(0, 101, 128)"
const C_MARGIN = "rgb(180, 59, 255)"
const C_PROFIT = "rgb(198, 179, 40)"

// ~8 weeks fill a typical panel; the rest (up to 20) scroll horizontally.
const PX_PER_WEEK = 132

// Compact label formatters for Recharts <LabelList />. Recharts v3 typed
// the formatter signature loosely (string | number | undefined), so accept any.
const fmtKLabel = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ""
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${Math.round(n / 1000)}k`
  return `${Math.round(n)}`
}
const fmtIntLabel = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ""
  return String(Math.round(n))
}
const fmtPct1Label = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return ""
  return `${n.toFixed(1)}%`
}

interface WeeklyProps {
  filters: CeoFilters
}

export function Weekly({ filters }: WeeklyProps) {
  const { data, isLoading, error } = useCeoWeekly({
    division: filters.division,
    team: filters.team,
    customer: filters.customer,
    contractType: filters.contractType,
  })
  const d = data?.data

  const weeks = (d?.weeks ?? []).map((r) => ({
    ...r,
    label: fmtWeekRange(r.week_start),
  }))

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Weekly" errors={[error]} />

      <div className="rounded-md border border-[#E5E7EB] bg-white p-3 text-xs text-[#6B7280]">
        Weekly panels are <strong>date-immutable</strong> — last 20 weeks regardless of Range
        (charts show ~8 weeks, scroll ← for the rest). Division, Team and Customer filters are honored.
      </div>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Loads vs Revenue by Week — Last 20 Weeks" loading={isLoading}>
          <WeekScrollChart count={weeks.length}>
            <ComposedChart data={weeks} margin={{ top: 18, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
              <YAxis
                yAxisId="left"
                tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 11 }}
              />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, name) =>
                name === "Revenue" ? fmtUsd(Number(v)) : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="revenue" fill={C_REVENUE} name="Revenue" barSize={28}>
                <LabelList dataKey="revenue" position="top" fontSize={10} fill="#134E4A" formatter={fmtKLabel} />
              </Bar>
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="loads"
                stroke={C_LOADS}
                name="Loads"
                dot={{ r: 3 }}
              >
                <LabelList dataKey="loads" position="top" fontSize={10} fill="#991B1B" formatter={fmtIntLabel} />
              </Line>
            </ComposedChart>
          </WeekScrollChart>
        </Panel>

        <Panel title="Profit & Margin % by Week — Last 20 Weeks" loading={isLoading}>
          <WeekScrollChart count={weeks.length}>
            <ComposedChart data={weeks} margin={{ top: 18, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
              <YAxis
                yAxisId="left"
                tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                tick={{ fontSize: 11 }}
              />
              <Tooltip formatter={(v, name) =>
                name === "Profit" ? fmtUsd(Number(v)) : `${Number(v).toFixed(2)}%`
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="profit" fill={C_PROFIT} name="Profit" barSize={28}>
                <LabelList dataKey="profit" position="top" fontSize={10} fill="#854D0E" formatter={fmtKLabel} />
              </Bar>
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="margin_pct"
                stroke={C_MARGIN}
                name="% Margin"
                dot={{ r: 3 }}
              >
                <LabelList dataKey="margin_pct" position="top" fontSize={10} fill="#6B21A8" formatter={fmtPct1Label} />
              </Line>
            </ComposedChart>
          </WeekScrollChart>
        </Panel>
      </section>

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="bg-[#DBEAFE] px-3 py-2 text-sm font-semibold text-[#1E3A8A]">
          Summary by Week
        </div>
        {isLoading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full text-[11px] tabular-nums">
              <thead className="sticky top-0 bg-[#DBEAFE] text-[#1E3A8A]">
                <tr>
                  <th className="px-2 py-1 text-left">Week</th>
                  <th className="px-1 py-1 text-right">Lanes</th>
                  <th className="px-1 py-1 text-right">Loads</th>
                  <th className="px-1 py-1 text-right">Revenue</th>
                  <th className="px-1 py-1 text-right">Profit</th>
                  <th className="px-1 py-1 text-right">Improvement</th>
                  <th className="px-1 py-1 text-right">% Margin</th>
                </tr>
              </thead>
              <tbody>
                {(d?.summary_by_week ?? []).map((r, i, arr) => {
                  // Rows are most-recent first; the chronologically previous
                  // week is the next row. Improvement = this − previous profit.
                  const prev = arr[i + 1]
                  const imp = prev ? r.profit - prev.profit : null
                  return (
                    <tr key={r.week_start} className="border-t border-[#F3F4F6]">
                      <td className="px-2 py-1">{fmtWeekRange(r.week_start)}</td>
                      <td className="px-1 py-1 text-right">{fmtCount(r.lanes)}</td>
                      <td className="px-1 py-1 text-right">{fmtCount(r.loads)}</td>
                      <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                      <td className="px-1 py-1 text-right">{fmtUsd(r.profit)}</td>
                      <td className="px-1 py-1 text-right">
                        {imp === null ? (
                          <span className="text-[#9CA3AF]">—</span>
                        ) : (
                          <span className={imp >= 0 ? "text-[#16A34A]" : "text-[#DC2626]"}>
                            {imp >= 0 ? "+" : "−"}
                            {fmtUsd(Math.abs(imp))}
                          </span>
                        )}
                      </td>
                      <td className="px-1 py-1 text-right">{fmtPct(r.margin_pct)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function Panel({
  title,
  loading,
  children,
}: {
  title: string
  loading?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#111827]">{title}</div>
      <div className="p-3">
        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  )
}

// Horizontally scrollable wrapper sizing the canvas to PX_PER_WEEK × weeks, so
// ~8 weeks fill a typical panel and the rest scroll; auto-scrolls to the right
// (most recent) on mount / data change.
function WeekScrollChart({ count, children }: { count: number; children: React.ReactElement }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollLeft = ref.current.scrollWidth
  }, [count])
  const innerWidth = Math.max(count * PX_PER_WEEK, 500)
  return (
    <div ref={ref} className="overflow-x-auto">
      <div style={{ width: innerWidth, minWidth: "100%" }}>
        <ResponsiveContainer width="100%" height={300}>
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
